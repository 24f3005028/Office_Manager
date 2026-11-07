package com.hstraders.widgets

import android.app.Application
import android.appwidget.AppWidgetManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Bundle
import android.view.View
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35], application = Application::class, qualifiers = "mdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class OfficeWidgetsTest {
  private lateinit var context: Context
  private lateinit var manager: AppWidgetManager
  @Before fun setup() {
    context = RuntimeEnvironment.getApplication()
    manager = AppWidgetManager.getInstance(context)
    WidgetStore.clear(context)
  }
  private fun data() = JSONObject().put("expiresAt", System.currentTimeMillis() + 60000)
    .put("taskHeading", "My office tasks").put("taskSummary", "3 open")
    .put("updatedLabel", "Updated today")
    .put("tasks", JSONArray(listOf("Dispatch\n7 Nov, 6 pm", "Follow up\n8 Nov, 6 pm", "Check stock\n9 Nov, 6 pm")))
    .put("party", JSONObject().put("name", "Test Party").put("amount", "₹1,23,456.78")
      .put("asOfLabel", "Statement as of 2026-11-07").put("availableUntil", System.currentTimeMillis() + 60000))
  private fun text(root: View, id: Int) = root.findViewById<TextView>(id).text.toString()
  private fun preview(root: View, name: String, width: Int, height: Int) {
    root.measure(View.MeasureSpec.makeMeasureSpec(width, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(height, View.MeasureSpec.EXACTLY))
    root.layout(0, 0, width, height)
    val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    root.draw(Canvas(bitmap))
    val folder = File(System.getProperty("office.widget.previewDir"))
    folder.mkdirs()
    File(folder, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    bitmap.recycle()
  }

  @Test fun taskRemoteViewsInflateAndAdaptToResize() {
    WidgetStore.write(context, data())
    val shadow = shadowOf(manager)
    val id = shadow.createWidget(TasksWidgetProvider::class.java, R.layout.office_widget)
    manager.updateAppWidgetOptions(id, Bundle().apply { putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 300) })
    val large = shadow.getViewFor(id)
    assertEquals("My office tasks", text(large, R.id.widget_title))
    assertTrue(text(large, R.id.widget_row1).contains("Dispatch"))
    assertEquals(View.VISIBLE, large.findViewById<View>(R.id.widget_row3).visibility)
    preview(large, "tasks-widget", 320, 300)
    manager.updateAppWidgetOptions(id, Bundle().apply { putInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 220) })
    assertEquals(View.GONE, shadow.getViewFor(id).findViewById<View>(R.id.widget_row2).visibility)
    assertEquals("Open tasks", text(shadow.getViewFor(id), R.id.widget_open))
  }

  @Test fun partyRemoteViewsShowNameAmountAndStatementDate() {
    WidgetStore.write(context, data())
    val shadow = shadowOf(manager)
    val id = shadow.createWidget(PartyWidgetProvider::class.java, R.layout.office_widget)
    val root = shadow.getViewFor(id)
    assertEquals("Test Party", text(root, R.id.widget_title))
    assertEquals("₹1,23,456.78", text(root, R.id.widget_summary))
    assertEquals("Statement as of 2026-11-07", text(root, R.id.widget_row1))
    assertEquals("Open statement", text(root, R.id.widget_open))
    preview(root, "party-widget", 320, 220)
    assertTrue(root.findViewById<View>(R.id.widget_open).performClick())
    assertEquals("hstraders-office://widget/party", shadowOf(context as Application).nextStartedActivity.dataString)
  }

  @Test fun expiredSnapshotDoesNotExposeTasksOrPartyBalance() {
    WidgetStore.write(context, data().put("expiresAt", System.currentTimeMillis() - 1000))
    val shadow = shadowOf(manager)
    for (provider in listOf(TasksWidgetProvider::class.java, PartyWidgetProvider::class.java)) {
      val id = shadow.createWidget(provider, R.layout.office_widget)
      val root = shadow.getViewFor(id)
      assertEquals("Set up widgets", text(root, R.id.widget_open))
      assertFalse(text(root, R.id.widget_summary).contains("1,23,456"))
      assertEquals(View.GONE, root.findViewById<View>(R.id.widget_row1).visibility)
    }
  }

  @Test fun expiredReportKeepsPartyButHidesItsOldBalance() {
    val snapshot = data()
    snapshot.getJSONObject("party").put("availableUntil", System.currentTimeMillis() - 1000)
    WidgetStore.write(context, snapshot)
    val shadow = shadowOf(manager)
    val id = shadow.createWidget(PartyWidgetProvider::class.java, R.layout.office_widget)
    val root = shadow.getViewFor(id)
    assertEquals("Test Party", text(root, R.id.widget_title))
    assertEquals("No available saved statement", text(root, R.id.widget_summary))
  }

  @Test fun longPartyNameStillLeavesTheActionVisibleAtMinimumSize() {
    val snapshot = data()
    snapshot.getJSONObject("party").put("name", "Test Party With A Long Textile Trading Account Name And Branch")
    WidgetStore.write(context, snapshot)
    val shadow = shadowOf(manager)
    val id = shadow.createWidget(PartyWidgetProvider::class.java, R.layout.office_widget)
    val root = shadow.getViewFor(id)
    root.measure(View.MeasureSpec.makeMeasureSpec(280, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(220, View.MeasureSpec.EXACTLY))
    root.layout(0, 0, 280, 220)
    val action = root.findViewById<View>(R.id.widget_open)
    assertTrue("Action bottom=${action.bottom}; title=${root.findViewById<View>(R.id.widget_title).height}; summary=${root.findViewById<View>(R.id.widget_summary).height}; row=${root.findViewById<View>(R.id.widget_row1).height}", action.bottom <= 220)
  }

  @Test fun clearingSnapshotRepaintsBothExistingWidgets() {
    WidgetStore.write(context, data())
    val shadow = shadowOf(manager)
    val task = shadow.createWidget(TasksWidgetProvider::class.java, R.layout.office_widget)
    val party = shadow.createWidget(PartyWidgetProvider::class.java, R.layout.office_widget)
    WidgetStore.clear(context)
    WidgetStore.update(context)
    for (id in listOf(task, party)) assertEquals("Set up widgets", text(shadow.getViewFor(id), R.id.widget_open))
    WidgetStore.write(context, data())
    WidgetStore.update(context)
    assertEquals(View.VISIBLE, shadow.getViewFor(party).findViewById<View>(R.id.widget_row1).visibility)
    assertEquals("Statement as of 2026-11-07", text(shadow.getViewFor(party), R.id.widget_row1))
  }
}
