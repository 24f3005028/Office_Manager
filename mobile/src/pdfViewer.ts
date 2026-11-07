import { Platform } from "react-native";
import { requireOptionalNativeModule } from "expo";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";

type Documents = { openPdf: (uri: string) => Promise<void> };
const documents =
  Platform.OS === "android"
    ? requireOptionalNativeModule<Documents>("OfficeDocuments")
    : null;

export async function openPdf(fileUri: string): Promise<void> {
  if (Platform.OS === "android") {
    if (!documents)
      throw new Error("Install the updated Android APK to open PDFs.");
    const contentUri = await FileSystem.getContentUriAsync(fileUri);
    await documents.openPdf(contentUri);
  } else if (await Sharing.isAvailableAsync()) {
    await Sharing.shareAsync(fileUri, {
      mimeType: "application/pdf",
      dialogTitle: "Open PDF",
    });
  } else throw new Error("A PDF viewer is unavailable on this device.");
}
