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

/** Widget confirmations use the same simple centered dialog as the main app. */
internal object TaskConfirmation {
  fun show(activity: Activity, title: String, repeat: String, confirm: () -> Unit): Dialog {
    fun dp(value: Int) = (value * activity.resources.displayMetrics.density).toInt()
    val blue = Color.rgb(0, 102, 204)
    val dialog = Dialog(activity)
    dialog.requestWindowFeature(Window.FEATURE_NO_TITLE)
    var handled = false
    val content = LinearLayout(activity).apply {
      orientation = LinearLayout.VERTICAL
      setPadding(0, 0, 0, 0)
      clipToOutline = true
      background = GradientDrawable().apply {
        setColor(Color.WHITE)
        cornerRadius = dp(14).toFloat()
      }
    }
    fun text(value: String, size: Float, color: Int, bold: Boolean = false) = TextView(activity).apply {
      text = value; textSize = size; setTextColor(color)
      if (bold) setTypeface(typeface, Typeface.BOLD)
      gravity = Gravity.CENTER
      setPadding(dp(20), dp(6), dp(20), dp(6))
    }
    content.addView(text("Mark task done?", 18f, Color.rgb(28, 28, 30), true),
      LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(16) })
    content.addView(text(title, 14f, Color.rgb(58, 58, 60)))
    if (repeat != "none") content.addView(text("The next $repeat occurrence will stay open.", 14f, Color.rgb(58, 58, 60)))
    content.addView(View(activity).apply { setBackgroundColor(Color.rgb(199, 199, 204)) },
      LinearLayout.LayoutParams(-1, dp(1)).apply { topMargin = dp(16) })
    fun button(label: String, primary: Boolean, action: () -> Unit): Button = Button(activity).apply {
      text = label; textSize = 16f; isAllCaps = false
      setTypeface(typeface, if (primary) Typeface.BOLD else Typeface.NORMAL)
      setTextColor(blue)
      stateListAnimator = null
      elevation = 0f
      background = GradientDrawable().apply {
        setColor(Color.WHITE)
      }
      minHeight = dp(50)
      setOnClickListener {
        if (!handled) { handled = true; dialog.dismiss(); action() }
      }
    }
    val actions = LinearLayout(activity).apply { orientation = LinearLayout.HORIZONTAL }
    actions.addView(button("Cancel", false) {}, LinearLayout.LayoutParams(0, -2, 1f))
    actions.addView(View(activity).apply { setBackgroundColor(Color.rgb(199, 199, 204)) }, LinearLayout.LayoutParams(dp(1), -1))
    actions.addView(button("Mark done", true, confirm), LinearLayout.LayoutParams(0, -2, 1f))
    content.addView(actions)
    val scroll = ScrollView(activity).apply { addView(content) }
    dialog.setContentView(scroll)
    dialog.setCanceledOnTouchOutside(true)
    dialog.setOnDismissListener { activity.finish() }
    dialog.window?.apply {
      setBackgroundDrawableResource(android.R.color.transparent)
      addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
      setDimAmount(0.32f)
      setGravity(Gravity.CENTER)
    }
    dialog.show()
    dialog.window?.setLayout(minOf(dp(320), (activity.resources.displayMetrics.widthPixels * 0.86f).toInt()), ViewGroup.LayoutParams.WRAP_CONTENT)
    return dialog
  }
}
