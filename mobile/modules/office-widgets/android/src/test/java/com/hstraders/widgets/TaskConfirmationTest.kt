package com.hstraders.widgets

import android.app.Activity
import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class TaskConfirmationTest {
  private fun descendants(view: View): List<View> = listOf(view) +
    if (view is ViewGroup) (0 until view.childCount).flatMap { descendants(view.getChildAt(it)) } else emptyList()

  @Test fun confirmationWritesOnlyOnceAndExplainsRepeatingTask() {
    val activity = Robolectric.buildActivity(Activity::class.java).setup().get()
    var writes = 0
    val dialog = TaskConfirmation.show(activity, "Example task", "daily") { writes++ }
    val views = descendants(dialog.window!!.decorView)
    val root = dialog.window!!.decorView
    root.measure(View.MeasureSpec.makeMeasureSpec(320, View.MeasureSpec.EXACTLY),
      View.MeasureSpec.makeMeasureSpec(480, View.MeasureSpec.AT_MOST))
    root.layout(0, 0, 320, root.measuredHeight)
    val bitmap = Bitmap.createBitmap(320, root.height, Bitmap.Config.ARGB_8888)
    root.draw(Canvas(bitmap))
    val folder = File(requireNotNull(System.getProperty("office.widget.previewDir")))
    folder.mkdirs()
    File(folder, "task-confirmation.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    assertTrue(views.filterIsInstance<TextView>().any { it.text.toString().contains("next daily occurrence") })
    val done = views.filterIsInstance<Button>().single { it.text == "Mark done" }
    done.performClick(); done.performClick()
    shadowOf(Looper.getMainLooper()).idle()
    assertEquals(1, writes)
    assertFalse(dialog.isShowing)
    assertTrue(activity.isFinishing)
  }

  @Test fun cancelButtonAndBackDismissalNeverCompleteTask() {
    for (cancelButton in listOf(true, false)) {
      val activity = Robolectric.buildActivity(Activity::class.java).setup().get()
      val dialog = TaskConfirmation.show(activity, "Example task", "none") { fail("Must not write") }
      val views = descendants(dialog.window!!.decorView)
      assertFalse(views.filterIsInstance<TextView>().any { it.text.toString().contains("next none occurrence") })
      if (cancelButton) views.filterIsInstance<Button>().single { it.text == "Cancel" }.performClick()
      else dialog.cancel()
      shadowOf(Looper.getMainLooper()).idle()
      assertFalse(dialog.isShowing)
      assertTrue(activity.isFinishing)
    }
  }
}
