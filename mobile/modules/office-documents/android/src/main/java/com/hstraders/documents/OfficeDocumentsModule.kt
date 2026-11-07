package com.hstraders.documents

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

internal object PdfViewer {
  const val DRIVE = "com.google.android.apps.docs"

  fun open(activity: Activity, uri: Uri) {
    // Only expose the downloaded local file, never the authenticated office URL.
    require(uri.scheme == "content" && uri.authority == "${activity.packageName}.FileSystemFileProvider" &&
      uri.query == null && uri.fragment == null) { "The downloaded PDF could not be opened safely." }
    fun intent() = Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/pdf")
      .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    try {
      // Do not hard-code a Drive activity class; it can change across Drive updates.
      activity.startActivity(intent().setPackage(DRIVE))
    } catch (_: ActivityNotFoundException) {
      try {
        activity.startActivity(intent())
      } catch (_: ActivityNotFoundException) {
        throw IllegalStateException("No PDF viewer found. Install Google Drive or another PDF reader, then try again.")
      }
    }
  }
}

class OfficeDocumentsModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("OfficeDocuments")
    AsyncFunction("openPdf") { uri: String ->
      PdfViewer.open(requireNotNull(appContext.currentActivity) { "Open the app and try again." }, Uri.parse(uri))
    }
  }
}
