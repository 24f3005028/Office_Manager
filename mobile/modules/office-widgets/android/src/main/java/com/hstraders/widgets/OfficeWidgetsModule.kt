package com.hstraders.widgets

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.util.AtomicFile
import android.view.View
import android.widget.RemoteViews
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import org.json.JSONObject
import java.io.File

class OfficeWidgetsModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("OfficeWidgets")
    AsyncFunction("saveSnapshot") { json: String ->
      require(json.length <= 64000) { "Widget snapshot is too large" }
      val context = requireNotNull(appContext.reactContext)
      val data = JSONObject(json)
      WidgetStore.write(context, data)
      WidgetStore.update(context)
    }
    AsyncFunction("clearSnapshot") {
      val context = requireNotNull(appContext.reactContext)
      WidgetStore.clear(context)
      WidgetStore.update(context)
    }
    AsyncFunction("hasWidgets") { kind: String ->
      require(kind == "tasks" || kind == "party")
      val context = requireNotNull(appContext.reactContext)
      AppWidgetManager.getInstance(context).getAppWidgetIds(WidgetStore.component(context, kind)).isNotEmpty()
    }
    AsyncFunction("pin") { kind: String ->
      require(kind == "tasks" || kind == "party")
      val context = requireNotNull(appContext.reactContext)
      val manager = AppWidgetManager.getInstance(context)
      if (Build.VERSION.SDK_INT >= 26 && manager.isRequestPinAppWidgetSupported) {
        manager.requestPinAppWidget(WidgetStore.component(context, kind), null, null)
      } else false
    }
  }
}

// No bearer token, phone number or PDF is written here. Keep snapshots outside backups.
internal object WidgetStore {
  private fun file(context: Context) = AtomicFile(File(context.noBackupFilesDir, "office-widgets.json"))
  @Synchronized fun write(context: Context, data: JSONObject) {
    val file = file(context)
    val stream = file.startWrite()
    try {
      stream.write(data.toString().toByteArray(Charsets.UTF_8))
      file.finishWrite(stream)
    } catch (error: Exception) {
      file.failWrite(stream)
      throw error
    }
  }
  @Synchronized fun clear(context: Context) { file(context).delete() }
  @Synchronized private fun read(context: Context): JSONObject? = try {
    file(context).openRead().use { JSONObject(it.readBytes().toString(Charsets.UTF_8)) }
      .takeIf { it.optLong("expiresAt") > System.currentTimeMillis() }
  } catch (_: Exception) { null }

  fun component(context: Context, kind: String) = ComponentName(context,
    if (kind == "tasks") TasksWidgetProvider::class.java else PartyWidgetProvider::class.java)

  fun update(context: Context) {
    val manager = AppWidgetManager.getInstance(context)
    for (kind in listOf("tasks", "party")) {
      for (id in manager.getAppWidgetIds(component(context, kind))) render(context, manager, id, kind)
    }
  }

  fun render(context: Context, manager: AppWidgetManager, id: Int, kind: String) {
    val data = read(context)
    val views = RemoteViews(context.packageName, R.layout.office_widget)
    val height = manager.getAppWidgetOptions(id).getInt(AppWidgetManager.OPTION_APPWIDGET_MIN_HEIGHT, 220)
    val rowLimit = if (height >= 280) 3 else if (height >= 240) 2 else if (height >= 200) 1 else 0
    views.setTextViewText(R.id.widget_title, if (kind == "tasks") data?.optString("taskHeading", "My office tasks") ?: "My office tasks" else "Party outstanding")
    var route = if (kind == "tasks") "tasks" else "party"
    if (data == null) {
      route = "setup"
      views.setTextViewText(R.id.widget_summary, "Open the app to connect and enable widgets")
      views.setTextViewText(R.id.widget_updated, "No current widget data")
      for (row in listOf(R.id.widget_row1, R.id.widget_row2, R.id.widget_row3)) views.setViewVisibility(row, View.GONE)
    } else {
      views.setTextViewText(R.id.widget_updated, data.optString("updatedLabel", "Saved data"))
      if (kind == "tasks") {
        views.setTextViewText(R.id.widget_summary, data.optString("taskSummary"))
        val rows = data.optJSONArray("tasks")
        for ((index, view) in listOf(R.id.widget_row1, R.id.widget_row2, R.id.widget_row3).withIndex()) {
          val text = rows?.optString(index, "") ?: ""
          views.setTextViewText(view, text)
          views.setViewVisibility(view, if (text.isEmpty() || index >= rowLimit) View.GONE else View.VISIBLE)
        }
      } else {
        val party = data.optJSONObject("party")
        if (party == null) route = "setup"
        views.setTextViewText(R.id.widget_title, party?.optString("name") ?: "Choose a party")
        val available = party != null && party.optLong("availableUntil") > System.currentTimeMillis()
        views.setTextViewText(R.id.widget_summary, if (available) party!!.optString("amount") else "No available saved statement")
        views.setTextViewText(R.id.widget_row1, if (available) party!!.optString("asOfLabel") else "Tap to create a fresh statement in the app")
        views.setViewVisibility(R.id.widget_row1, View.VISIBLE)
        views.setTextViewText(R.id.widget_row2, "Saved balance • fresh reports are manual")
        views.setViewVisibility(R.id.widget_row2, if (height >= 260) View.VISIBLE else View.GONE)
        views.setViewVisibility(R.id.widget_row3, View.GONE)
      }
    }
    views.setTextViewText(R.id.widget_open, if (route == "setup") "Set up widgets" else if (kind == "tasks") "Open tasks" else "Open statement")
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse("hstraders-office://widget/$route"))
      .setComponent(ComponentName(context.packageName, "${context.packageName}.MainActivity"))
      .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    val pending = PendingIntent.getActivity(context, id, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    views.setOnClickPendingIntent(R.id.widget_root, pending)
    views.setOnClickPendingIntent(R.id.widget_open, pending)
    manager.updateAppWidget(id, views)
  }
}

class TasksWidgetProvider : AppWidgetProvider() {
  override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
    for (id in ids) WidgetStore.render(context, manager, id, "tasks")
  }
  override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: Bundle) {
    WidgetStore.render(context, manager, id, "tasks")
  }
}
class PartyWidgetProvider : AppWidgetProvider() {
  override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
    for (id in ids) WidgetStore.render(context, manager, id, "party")
  }
  override fun onAppWidgetOptionsChanged(context: Context, manager: AppWidgetManager, id: Int, options: Bundle) {
    WidgetStore.render(context, manager, id, "party")
  }
}
