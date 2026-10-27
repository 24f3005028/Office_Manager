import cors from "cors";
import express, { type NextFunction, type Request, type Response } from "express";
import multer from "multer";
import type { BridgeConfig } from "../config.js";
import { MAX_PDF_BYTES, validateAllowedRoots, validateUploadedPdf } from "../domain/path-validation.js";
import { isRoutingId } from "../domain/contact-filter.js";
import { bounded, systemClock } from "../domain/clock.js";
import { BridgeError, invalidRequest } from "../domain/errors.js";
import { OperationSender } from "../queue/operation-sender.js";
import type { WhatsappClient } from "../client/whatsapp-client.js";

function requireApiKey(config: BridgeConfig) {
  return (request: Request, _response: Response, next: NextFunction) => {
    if (!config.apiKey) return next();
    const bearer = request.header("authorization")?.replace(/^Bearer\s+/i, "");
    if (request.header("x-api-key") !== config.apiKey && bearer !== config.apiKey) {
      return next(new BridgeError(401, "unauthorized", "Unauthorized"));
    }
    next();
  };
}

function textValue(value: unknown): string { return typeof value === "string" ? value : ""; }

function commandFields(request: Request) {
  const contactId = textValue(request.body?.contact_id ?? request.body?.to).trim();
  const operationId = textValue(request.body?.operation_id);
  if (!isRoutingId(contactId)) throw invalidRequest("Invalid contact routing identity");
  if (!operationId.trim() || operationId.length > 200 || /[\x00-\x1f\x7f]/.test(operationId)) throw invalidRequest("A valid operation_id is required");
  let generation: unknown = request.body?.generation;
  if (request.is("multipart/form-data") && typeof generation === "string" && /^\d+$/.test(generation)) generation = Number(generation);
  if (generation !== undefined && (typeof generation !== "number" || !Number.isSafeInteger(generation) || generation < 0)) throw invalidRequest("Invalid generation");
  return { contactId, operationId, generation: generation as number | undefined };
}

export function createApp(config: BridgeConfig, whatsapp: WhatsappClient, sender = new OperationSender(config, whatsapp)) {
  const app = express();
  // Multer passes these through to Busboy. The installed @types/multer version
  // predates the two newer parser limits, so keep the compatibility cast local.
  const multipartLimits = {
    fileSize: MAX_PDF_BYTES, files: 1, fields: 8, fieldSize: 16 * 1024, parts: 9,
    fieldNameSize: 256, headerPairs: 100, fieldArrayIndexLimit: 100,
  };
  const upload = multer({
    storage: multer.memoryStorage(),
    limits: multipartLimits as unknown as NonNullable<Parameters<typeof multer>[0]>["limits"],
  });
  app.disable("x-powered-by");
  app.locals.closeSends = () => sender.close();
  app.use((request, response, next) => {
    response.setHeader("Cache-Control", "no-store");
    const origin = request.header("origin");
    // CORS response headers alone do NOT prevent cross-origin POST mutations.
    if (origin !== undefined && !config.corsOrigins.includes(origin)) {
      return next(new BridgeError(403, "origin_forbidden", "Browser origin is not allowed"));
    }
    next();
  });
  app.use(cors({ origin: config.corsOrigins.length ? config.corsOrigins : false }));
  app.use(requireApiKey(config));
  app.use(express.json({ limit: "256kb" }));

  app.get("/status", (_request, response) => response.json(whatsapp.status()));
  app.post("/start", async (_request, response, next) => {
    try { await whatsapp.start(); response.json(whatsapp.status()); } catch (error) { next(error); }
  });
  app.post("/reconnect", async (_request, response, next) => {
    try { await whatsapp.reconnect(); response.json(whatsapp.status()); } catch (error) { next(error); }
  });

  app.put("/allowed-roots", async (request, response, next) => {
    try {
      const roots = await bounded(validateAllowedRoots(request.body?.roots), config.fileReadTimeoutMs, systemClock);
      config.allowedRoots = roots;
      response.json({ roots });
    } catch (error) {
      next(error instanceof BridgeError ? error : new BridgeError(400, "invalid_roots", "Allowed roots could not be validated"));
    }
  });

  app.get("/qr", (_request, response, next) => {
    const qr = whatsapp.qr();
    if (!qr) return next(new BridgeError(404, "qr_unavailable", "QR code unavailable"));
    response.type("svg").send(qr);
  });
  app.get("/contacts", async (_request, response, next) => {
    try { response.json(await whatsapp.contacts()); } catch (error) { next(error); }
  });

  app.post("/send-text", async (request, response, next) => {
    try {
      const fields = commandFields(request);
      const text = textValue(request.body?.text);
      if (!text.trim() || text.length > 4096) throw invalidRequest("Text must contain 1–4096 characters");
      response.json(await sender.send({ ...fields, kind: "text", text }));
    } catch (error) { next(error); }
  });

  app.post("/send-document", upload.single("file"), async (request, response, next) => {
    try {
      const fields = commandFields(request);
      const rawCaption = request.body?.caption;
      // The backend serializes an absent message as JSON null. Treat it the
      // same as an omitted caption instead of rejecting an otherwise valid send.
      if (rawCaption !== undefined && rawCaption !== null && typeof rawCaption !== "string") throw invalidRequest("Invalid caption");
      const caption = textValue(rawCaption) || undefined;
      if (caption && caption.length > 4096) throw invalidRequest("Caption is too long");
      if (request.file) {
        if (request.body?.file_path !== undefined || request.body?.path !== undefined) throw invalidRequest("Supply either a PDF upload or a path");
        validateUploadedPdf(request.file.originalname, request.file.buffer);
        response.json(await sender.send({ ...fields, kind: "upload", buffer: request.file.buffer, filename: request.file.originalname, caption }));
      } else {
        const filePath = textValue(request.body?.file_path ?? request.body?.path).trim();
        if (!filePath || filePath.length > 4096) throw invalidRequest("A PDF path is required");
        response.json(await sender.send({ ...fields, kind: "path", filePath, caption }));
      }
    } catch (error) { next(error); }
  });

  app.use((_request, _response, next) => next(new BridgeError(404, "not_found", "Route not found")));
  app.use((error: unknown, _request: Request, response: Response, _next: NextFunction) => {
    let publicError: BridgeError;
    if (error instanceof BridgeError) publicError = error;
    else if (error instanceof multer.MulterError) {
      publicError = new BridgeError(error.code === "LIMIT_FILE_SIZE" ? 413 : 400, "upload_rejected", "The uploaded file was rejected");
    } else {
      const parser = error as { type?: string; status?: number } | null;
      if (parser && ["entity.parse.failed", "entity.too.large", "encoding.unsupported", "charset.unsupported", "request.aborted", "request.size.invalid"].includes(parser.type ?? "")) {
        publicError = new BridgeError(parser.status && parser.status >= 400 && parser.status < 500 ? parser.status : 400, "invalid_body", "The request body was rejected");
      } else {
        // Malformed multipart streams may be plain Busboy errors, not MulterError.
        publicError = new BridgeError(_request.is("multipart/form-data") ? 400 : 502, "bridge_error", "The bridge operation failed");
      }
    }
    response.status(publicError.status).json(publicError.json());
  });
  return app;
}

export function closeApp(app: express.Express): void { app.locals.closeSends?.(); }

export function startServer(config: BridgeConfig, app: express.Express): Promise<import("node:http").Server> {
  return new Promise((resolve, reject) => {
    const server = app.listen(config.port, config.host);
    const failed = (error: Error) => {
      const code = (error as NodeJS.ErrnoException).code;
      reject(new BridgeError(
        503,
        "listen_failed",
        code === "EADDRINUSE"
          ? `The bridge could not listen on ${config.host}:${config.port}; the port is already in use`
          : "The bridge could not listen on its configured address",
      ));
    };
    server.once("error", failed);
    server.once("listening", () => {
      server.removeListener("error", failed);
      server.on("error", () => console.error("Bridge HTTP server error"));
      resolve(server);
    });
  });
}
