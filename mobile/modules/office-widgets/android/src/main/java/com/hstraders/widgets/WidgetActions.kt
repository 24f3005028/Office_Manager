package com.hstraders.widgets

import android.app.Activity
import android.app.AlertDialog
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import expo.modules.notifications.service.NotificationsService
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.net.ssl.HttpsURLConnection

// A separate encrypted credential is required because Android renders widget actions
// without starting React. It is never placed in RemoteViews, intents or backups.
internal object WidgetConnection {
  private const val ALIAS = "office-widget-connection-v1"
  private fun file(context: Context) = AtomicFile(File(context.noBackupFilesDir, "office-widget-connection.enc"))
  private fun key(): SecretKey {
    val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    return (store.getKey(ALIAS, null) as? SecretKey) ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
      init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
    }.generateKey()
  }
  @Synchronized fun write(context: Context, data: JSONObject) {
    val url = URL(data.getString("url"))
    require(url.protocol == "https" && url.userInfo == null && url.query == null && url.ref == null && url.path in listOf("", "/"))
    require(data.getString("token").length in 16..4096 && data.getLong("expiresAt") > System.currentTimeMillis())
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
    val bytes = cipher.iv + cipher.doFinal(data.toString().toByteArray(Charsets.UTF_8))
    val target = file(context); val stream = target.startWrite()
    try { stream.write(bytes); target.finishWrite(stream) } catch (e: Exception) { target.failWrite(stream); throw e }
  }
  @Synchronized fun read(context: Context): JSONObject? = try {
    val bytes = file(context).openRead().use { it.readBytes() }
    val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes.copyOfRange(0, 12))) }
    JSONObject(cipher.doFinal(bytes.copyOfRange(12, bytes.size)).toString(Charsets.UTF_8)).takeIf { it.getLong("expiresAt") > System.currentTimeMillis() }
  } catch (_: Exception) { null }
  @Synchronized fun clear(context: Context) { file(context).delete() }
  fun clearIfSame(context: Context, session: JSONObject): Boolean = synchronized(WidgetStore) {
    if (!same(context, session)) false
    else { clear(context); WidgetStore.clear(context); true }
  }
  fun same(context: Context, session: JSONObject) = read(context)?.let { it.optString("token") == session.optString("token") && it.optString("url") == session.optString("url") } == true
  fun fingerprint(session: JSONObject): String = MessageDigest.getInstance("SHA-256")
    .digest((session.getString("url") + "\n" + session.getString("token")).toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}

internal class WidgetHttpError(val code: Int) : Exception()
internal fun taskDate(value: String): Date = requireNotNull(
  SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ENGLISH).apply { isLenient = false }
    .parse(value.replace(Regex("\\.\\d+(?=[Z+-])"), "")))
internal object TaskAction {
  // Versions are checked locally and by the server. A stale checkbox never advances
  // the next occurrence of a repeating task; a failed POST is never retried blindly.
  fun complete(rows: JSONArray, id: String, version: Int, post: (String, JSONObject) -> Unit): Boolean {
    require(id.matches(Regex("[a-f0-9]{32}")) && version > 0)
    val task = (0 until rows.length()).map { rows.getJSONObject(it) }.find { it.optString("id") == id } ?: return false
    if (task.optString("status") != "open" || task.optInt("version") != version) return false
    post("/tasks/$id/complete", JSONObject().put("version", version))
    return true
  }
}

class WidgetTaskWorker(context: Context, parameters: WorkerParameters) : Worker(context, parameters) {
  private fun request(session: JSONObject, path: String, body: JSONObject? = null): String {
    val connection = URL(session.getString("url").trimEnd('/') + "/mobile/v1" + path).openConnection() as HttpsURLConnection
    try {
      connection.connectTimeout = 12000; connection.readTimeout = 15000
      connection.instanceFollowRedirects = false
      connection.setRequestProperty("Authorization", "Bearer " + session.getString("token"))
      connection.setRequestProperty("Accept", "application/json")
      if (body != null) {
        check(WidgetConnection.same(applicationContext, session))
        connection.requestMethod = "POST"; connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
      }
      if (connection.responseCode !in 200..299) throw WidgetHttpError(connection.responseCode)
      return connection.inputStream.bufferedReader().use { it.readText() }
    } finally { connection.disconnect() }
  }
  override fun doWork(): Result {
    val context = applicationContext
    val session = WidgetConnection.read(context) ?: return Result.success()
    if (inputData.getString("connection") != WidgetConnection.fingerprint(session)) return Result.success()
    val original = WidgetStore.read(context) ?: return Result.success()
    var message: String? = null
    try {
      var rows = JSONArray(request(session, "/tasks"))
      val id = inputData.getString("taskId")
      if (id != null) {
        val done = TaskAction.complete(rows, id, inputData.getInt("version", 0)) { path, body -> request(session, path, body) }
        if (done) {
          val completed = (0 until rows.length()).map { rows.getJSONObject(it) }.first { it.getString("id") == id }
          val due = taskDate(completed.getString("due_at")).time
          NotificationsService.removeScheduledNotification(context, "office-task-$id-$due")
          message = "Task completed"
        } else message = "Task changed · refreshed"
        rows = JSONArray(request(session, "/tasks"))
      }
      if (!WidgetConnection.same(context, session)) return Result.success()
      val snapshot = snapshot(rows, original, session.getLong("expiresAt"))
      if (message != null) snapshot.put("actionMessage", message)
      WidgetStore.writeIfCurrent(context, snapshot, original.optString("generation"))
    } catch (error: Exception) {
      if (!WidgetConnection.same(context, session)) return Result.success()
      if (error is WidgetHttpError && error.code in listOf(401, 403)) {
        WidgetConnection.clearIfSame(context, session)
      } else {
        // Keep the last verified list and timestamp. Never claim success offline.
        original.put("actionMessage", if (inputData.getString("taskId") != null) "Could not confirm · open tasks to check" else "Offline · showing saved tasks")
        WidgetStore.writeIfCurrent(context, original, original.optString("generation"))
      }
    }
    WidgetStore.update(context)
    return Result.success() // User decides when to retry; no automatic writes.
  }
  companion object {
    fun enqueue(context: Context, id: String? = null, version: Int = 0) {
      val session = WidgetConnection.read(context) ?: return
      WidgetStore.read(context)?.let { snapshot ->
        val generation = snapshot.optString("generation")
        snapshot.put("actionMessage", if (id == null) "Refreshing…" else "Completing task…")
        WidgetStore.writeIfCurrent(context, snapshot, generation)
        WidgetStore.update(context)
      }
      val data = Data.Builder().putString("taskId", id).putInt("version", version)
        .putString("connection", WidgetConnection.fingerprint(session)).build()
      WorkManager.getInstance(context).enqueueUniqueWork("office-widget-actions", ExistingWorkPolicy.APPEND_OR_REPLACE,
        OneTimeWorkRequestBuilder<WidgetTaskWorker>().setInputData(data).addTag("office-widget-actions").build())
    }
    internal fun snapshot(rows: JSONArray, old: JSONObject, expiry: Long): JSONObject {
      val now = System.currentTimeMillis()
      val format = SimpleDateFormat("d MMM, h:mm a", Locale.ENGLISH).apply { timeZone = TimeZone.getTimeZone("Asia/Kolkata") }
      fun date(row: JSONObject): Date = taskDate(row.getString("due_at"))
      val open = (0 until rows.length()).map { rows.getJSONObject(it) }.filter { row -> row.optString("status") == "open" &&
        (old.optString("scope") != "mine" || (0 until row.getJSONArray("assignees").length()).any { row.getJSONArray("assignees").getString(it) == old.optString("userId") }) }
        .sortedWith(compareBy({ date(it).time }, { it.getString("id") }))
      val overdue = open.count { date(it).time < now }
      return JSONObject().put("expiresAt", minOf(expiry, now + 86400000)).put("scope", old.optString("scope"))
        .put("userId", old.optString("userId")).put("taskHeading", old.optString("taskHeading", "Office tasks"))
        .put("taskSummary", if (open.isEmpty()) "No open tasks" else "${open.size} open" + if (overdue > 0) " · $overdue overdue" else "")
        .put("tasks", JSONArray(open.take(3).map { it.getString("title").take(100) + "\n" + format.format(date(it)) + if (it.getString("repeat_rule") != "none") " · ${it.getString("repeat_rule")}" else "" }))
        .put("taskRows", JSONArray(open.take(3).map { row -> JSONObject().apply {
          for (field in listOf("id", "version", "title", "due_at", "repeat_rule")) put(field, row.get(field))
        } })).put("updatedLabel", "Updated " + format.format(Date(now)))
    }
  }
}

class WidgetRefreshReceiver : BroadcastReceiver() {
  override fun onReceive(context: Context, intent: Intent) { WidgetTaskWorker.enqueue(context) }
}

class WidgetCompleteActivity : Activity() {
  override fun onCreate(state: Bundle?) {
    super.onCreate(state)
    val id = intent.getStringExtra("taskId"); val version = intent.getIntExtra("version", 0)
    val rows = WidgetStore.read(this)?.optJSONArray("taskRows")
    val task = rows?.let { (0 until it.length()).map { n -> it.getJSONObject(n) }.find { row -> row.optString("id") == id && row.optInt("version") == version } }
    if (task == null || WidgetConnection.read(this) == null) { finish(); return }
    val repeat = task.optString("repeat_rule", "none")
    AlertDialog.Builder(this).setTitle("Mark task done?").setMessage(task.getString("title") + if (repeat != "none") "\nThe next $repeat occurrence will stay open." else "")
      .setNegativeButton("Cancel") { _, _ -> finish() }
      .setPositiveButton("Mark done") { _, _ -> WidgetTaskWorker.enqueue(this, id, version); finish() }
      .setOnCancelListener { finish() }.show()
  }
}
