package com.hstraders.widgets

import android.app.Activity
import android.app.Dialog
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Widget confirmations use the same light, rounded sheet as the main app. */
internal object TaskConfirmation {
  fun show(activity: Activity, title: String, repeat: String, confirm: () -> Unit): Dialog {
    fun dp(value: Int) = (value * activity.resources.displayMetrics.density).toInt()
    val navy = Color.rgb(23, 59, 96)
    val dialog = Dialog(activity)
    dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
    var handled = false
    val content = LinearLayout(activity).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(dp(24), dp(12), dp(24), dp(24))
      background = GradientDrawable().apply {
        setColor(Color.WHITE)
        cornerRadii = floatArrayOf(dp(28).toFloat(), dp(28).toFloat(), dp(28).toFloat(), dp(28).toFloat(), 0f, 0f, 0f, 0f)
      }
    }
    fun text(value: String, size: Float, color: Int, bold: Boolean = false) = TextView(activity).apply {
      text = value; textSize = size; setTextColor(color)
      if (bold) setTypeface(typeface, Typeface.BOLD)
      setPadding(0, dp(8), 0, dp(8))
    }
    content.addView(View(activity).apply {
      background = GradientDrawable().apply { setColor(Color.rgb(216, 225, 232)); cornerRadius = dp(2).toFloat() }
    }, LinearLayout.LayoutParams(dp(40), dp(4)).apply { gravity = Gravity.CENTER_HORIZONTAL; bottomMargin = dp(20) })
    content.addView(text("Mark task done?", 25f, navy, true))
    content.addView(text(title, 17f, Color.rgb(23, 47, 69), true))
    if (repeat != "none") content.addView(text("The next $repeat occurrence will stay open.", 16f, Color.rgb(88, 107, 127)))
    fun button(label: String, primary: Boolean, action: () -> Unit): Button = Button(activity).apply {
      text = label; textSize = 16f; isAllCaps = false
      setTypeface(typeface, Typeface.BOLD)
      setTextColor(if (primary) Color.WHITE else navy)
      background = GradientDrawable().apply {
        setColor(if (primary) navy else Color.rgb(240, 244, 247)); cornerRadius = dp(18).toFloat()
      }
      minHeight = dp(54)
      setOnClickListener {
        if (!handled) { handled = true; dialog.dismiss(); action() }
      }
    }
    content.addView(button("Mark done", true, confirm), LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(20) })
    content.addView(button("Cancel", false) {}, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(10) })
    val scroll = ScrollView(activity).apply { addView(content) }
    dialog.setContentView(scroll)
    dialog.setCanceledOnTouchOutside(true)
    dialog.setOnDismissListener { activity.finish() }
    dialog.window?.apply {
      setBackgroundDrawableResource(android.R.color.transparent)
      addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
      setDimAmount(0.4f)
      setGravity(Gravity.BOTTOM)
    }
    dialog.show()
    dialog.window?.setLayout(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
    return dialog
  }
}
