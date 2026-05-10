package ai.phronetic.screener

import android.content.Context
import androidx.core.content.edit

/**
 * SharedPreferences wrapper.
 *
 * Provider-managed (hidden from users):
 *   • Server URL            → hardcoded in app, never shown
 *   • Assigned number       → stored internally for backend use, never shown to user
 *   • Anthropic/Deepgram    → backend holds provider keys
 *
 * User-managed:
 *   • Auth token            → obtained from /v1/auth/otp/verify
 *   • Screener enabled      → toggle on/off
 *   • Onboarding complete   → one-time flag
 */
object Config {
    /** Hardcoded provider backend. Never exposed to users. */
    const val SERVER_URL = "https://pickr.phronetic.ai"

    private const val PREFS_NAME    = "avrs_screener"
    private const val KEY_AUTH_TOKEN = "auth_token"
    private const val KEY_ASSIGNED_NUM = "assigned_pickr_number"
    private const val KEY_ENABLED   = "screener_enabled"
    private const val KEY_ONBOARDED = "onboarding_complete"

    fun getAuthToken(context: Context): String =
        prefs(context).getString(KEY_AUTH_TOKEN, "") ?: ""

    fun setAuthToken(context: Context, token: String) =
        prefs(context).edit { putString(KEY_AUTH_TOKEN, token.trim()) }

    /** Internal use only — never displayed to users. */
    fun getAssignedNumber(context: Context): String =
        prefs(context).getString(KEY_ASSIGNED_NUM, "") ?: ""

    fun setAssignedNumber(context: Context, number: String) =
        prefs(context).edit { putString(KEY_ASSIGNED_NUM, number.trim()) }

    fun isEnabled(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ENABLED, true)

    fun setEnabled(context: Context, enabled: Boolean) =
        prefs(context).edit { putBoolean(KEY_ENABLED, enabled) }

    fun isOnboarded(context: Context): Boolean =
        prefs(context).getBoolean(KEY_ONBOARDED, false)

    fun setOnboarded(context: Context, complete: Boolean) =
        prefs(context).edit { putBoolean(KEY_ONBOARDED, complete) }

    fun isAuthenticated(context: Context): Boolean =
        getAuthToken(context).isNotBlank()

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}

enum class ScreeningMode { OFFLINE, LLM }
