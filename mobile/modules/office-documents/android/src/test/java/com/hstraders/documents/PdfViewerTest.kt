package com.hstraders.documents

import android.app.Activity
import android.app.Application
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class PdfViewerTest {
  class ViewerActivity : Activity() {
    val attempts = mutableListOf<Intent>()
    var driveMissing = false
    var allMissing = false
    var denyDrive = false
    override fun startActivity(intent: Intent) {
      attempts.add(intent)
      if (denyDrive) throw SecurityException("Access denied")
      if (allMissing || (driveMissing && intent.`package` == PdfViewer.DRIVE)) throw ActivityNotFoundException()
    }
  }
  private lateinit var activity: ViewerActivity
  private lateinit var uri: Uri
  @Before fun setup() {
    activity = Robolectric.buildActivity(ViewerActivity::class.java).setup().get()
    uri = Uri.parse("content://${activity.packageName}.FileSystemFileProvider/cache/office-test/123%20-%20Test%20Party.pdf")
  }
  @Test fun opensLocalPdfInDriveWithoutPrintingOrWriteAccess() {
    PdfViewer.open(activity, uri)
    val intent = activity.attempts.single()
    assertEquals(Intent.ACTION_VIEW, intent.action)
    assertEquals("application/pdf", intent.type)
    assertEquals(PdfViewer.DRIVE, intent.`package`)
    assertEquals(uri, intent.data)
    assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, intent.flags)
    assertNull(intent.component)
    assertNull(intent.extras)
  }
  @Test fun missingDriveFallsBackToAnotherPdfViewer() {
    activity.driveMissing = true
    PdfViewer.open(activity, uri)
    assertEquals(2, activity.attempts.size)
    val fallback = activity.attempts.last()
    assertNull(fallback.`package`)
    assertEquals(Intent.ACTION_VIEW, fallback.action)
    assertEquals("application/pdf", fallback.type)
    assertEquals(uri, fallback.data)
    assertEquals(Intent.FLAG_GRANT_READ_URI_PERMISSION, fallback.flags)
  }
  @Test fun noViewerGivesAnActionableErrorWithoutPrintFallback() {
    activity.allMissing = true
    try { PdfViewer.open(activity, uri); fail("Expected no-viewer message") }
    catch (error: IllegalStateException) { assertTrue(error.message!!.contains("Install Google Drive")) }
    assertEquals(2, activity.attempts.size)
  }
  @Test fun rejectsOfficeUrlsAndOtherProvidersWithoutLaunchingAnything() {
    for (value in listOf("https://office.invalid/mobile/v1/reports/id/pdf", "file:///private/test.pdf",
      "content://other.app.provider/document.pdf", "$uri?token=secret", "$uri#fragment")) {
      try { PdfViewer.open(activity, Uri.parse(value)); fail("Expected invalid URI") }
      catch (_: IllegalArgumentException) { }
    }
    assertTrue(activity.attempts.isEmpty())
  }
  @Test fun permissionFailureIsNotMaskedByLaunchingAnotherApp() {
    activity.denyDrive = true
    try { PdfViewer.open(activity, uri); fail("Expected permission failure") }
    catch (_: SecurityException) { assertEquals(1, activity.attempts.size) }
  }
}
