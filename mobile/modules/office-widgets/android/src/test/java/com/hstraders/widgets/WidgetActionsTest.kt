package com.hstraders.widgets

import android.app.Application
import android.appwidget.AppWidgetManager
import android.os.Bundle
import android.view.View
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class)
class WidgetActionsTest {
  private val id = "a".repeat(32)
  private fun task(version: Int = 2, status: String = "open") = JSONObject()
    .put("id", id).put("version", version).put("status", status).put("title", "Test dispatch")
    .put("repeat_rule", "daily").put("due_at", "2026-11-07T18:00:00+05:30").put("assignees", JSONArray(listOf("me")))
  @Test fun duplicateCheckboxCannotCompleteNextRepeatingOccurrence() {
    var calls = 0
    val rows = JSONArray().put(task())
    assertTrue(TaskAction.complete(rows, id, 2) { path, body ->
      assertEquals("/tasks/$id/complete", path); assertEquals(2, body.getInt("version")); calls++
      rows.getJSONObject(0).put("version", 3)
    })
    assertFalse(TaskAction.complete(rows, id, 2) { _, _ -> calls++ })
    assertEquals(1, calls)
  }
  @Test fun completedOrRemovedTasksNeverWrite() {
    assertFalse(TaskAction.complete(JSONArray().put(task(status = "done")), id, 2) { _, _ -> fail("Must not write") })
    assertFalse(TaskAction.complete(JSONArray(), id, 2) { _, _ -> fail("Must not write") })
  }
  @Test fun ambiguousNetworkFailureIsNotRetried() {
    var calls = 0
    try {
      TaskAction.complete(JSONArray().put(task()), id, 2) { _, _ -> calls++; throw java.io.IOException("Connection lost") }
      fail("Should propagate uncertainty")
    } catch (_: java.io.IOException) { assertEquals(1, calls) }
  }
  @Test fun snapshotPreservesScopeAndUsesServerStateAfterRepeat() {
    val old = JSONObject().put("scope", "mine").put("userId", "me").put("taskHeading", "My office tasks")
    val other = task().put("id", "b".repeat(32)).put("assignees", JSONArray(listOf("other")))
    val rows = JSONArray().put(task(3).put("due_at", "2026-11-08T18:00:00+05:30")).put(other)
    val snapshot = WidgetTaskWorker.snapshot(rows, old, System.currentTimeMillis() + 60000)
    assertEquals(1, snapshot.getJSONArray("taskRows").length())
    assertEquals(3, snapshot.getJSONArray("taskRows").getJSONObject(0).getInt("version"))
    assertTrue(snapshot.getJSONArray("tasks").getString(0).contains("daily"))
    assertFalse(snapshot.has("token"))
  }
  @Test fun lateRefreshCannotRestoreLoggedOutOrReconfiguredData() {
    val context = RuntimeEnvironment.getApplication()
    val first = JSONObject().put("expiresAt", System.currentTimeMillis() + 60000)
    WidgetStore.write(context, first)
    val generation = WidgetStore.read(context)!!.getString("generation")
    WidgetStore.clear(context)
    WidgetStore.writeIfCurrent(context, first, generation)
    assertNull(WidgetStore.read(context))
    WidgetStore.write(context, JSONObject().put("expiresAt", System.currentTimeMillis() + 60000).put("scope", "mine"))
    WidgetStore.writeIfCurrent(context, first, generation)
    assertEquals("mine", WidgetStore.read(context)!!.getString("scope"))
  }
  @Test fun checkboxLaunchesPrivateConfirmationAndAddOpensNewTask() {
    val context = RuntimeEnvironment.getApplication()
    val manager = AppWidgetManager.getInstance(context)
    WidgetStore.write(context, JSONObject().put("expiresAt", System.currentTimeMillis() + 60000)
      .put("tasks", JSONArray(listOf("Test dispatch\nToday"))).put("taskRows", JSONArray().put(task())))
    val shadow = shadowOf(manager)
    val widget = shadow.createWidget(TasksWidgetProvider::class.java, R.layout.office_widget)
    manager.updateAppWidgetOptions(widget, Bundle().apply { putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 220) })
    val root = shadow.getViewFor(widget)
    assertTrue(root.findViewById<View>(R.id.widget_done1).performClick())
    val intent = shadowOf(context).nextStartedActivity
    assertEquals(WidgetCompleteActivity::class.java.name, intent.component!!.className)
    assertEquals(id, intent.getStringExtra("taskId"))
    assertTrue(root.findViewById<View>(R.id.widget_add).performClick())
    assertEquals("hstraders-office://widget/new-task", shadowOf(context).nextStartedActivity.dataString)
  }
}
