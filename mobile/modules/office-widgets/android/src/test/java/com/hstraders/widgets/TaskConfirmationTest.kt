package com.hstraders.widgets

import android.app.Activity
import android.app.Application
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

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class TaskConfirmationTest {
  private fun descendants(view: View): List<View> = listOf(view) +
    if (view is ViewGroup) (0 until view.childCount).flatMap { descendants(view.getChildAt(it)) } else emptyList()

  @Test fun confirmationWritesOnlyOnceAndExplainsRepeatingTask() {
    val activity = Robolectric.buildActivity(Activity::class.java).setup().get()
    var writes = 0
    val dialog = TaskConfirmation.show(activity, "Example task", "daily") { writes++ }
    val views = descendants(dialog.window!!.decorView)
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
