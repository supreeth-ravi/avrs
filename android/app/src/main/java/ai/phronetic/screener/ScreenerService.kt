package ai.phronetic.screener

import android.content.Intent
import android.telecom.Call
import android.telecom.CallScreeningService
import android.util.Log
import ai.phronetic.screener.data.db.AppDatabase
import ai.phronetic.screener.data.repository.ContactRuleRepository
import ai.phronetic.screener.ui.ScreeningOverlayActivity

/**
 * Android CallScreeningService — intercepts incoming calls before they ring.
 *
 * With the Exotel SIP/WebSocket flow, the actual AI conversation happens
 * server-side.  This service simply:
 *   1. Checks whitelist / blocklist
 *   2. Mutes the ringer for unknown callers
 *   3. Launches the overlay so the user can monitor the backend screening
 *   4. The overlay connects to /ws/screen on the AVRS backend
 */
class ScreenerService : CallScreeningService() {

    override fun onScreenCall(callDetails: Call.Details) {
        val caller = callDetails.handle?.schemeSpecificPart ?: "unknown"
        Log.d(TAG, "Screening call from: $caller")

        if (!Config.isEnabled(applicationContext)) {
            Log.d(TAG, "Screener disabled — allowing call through")
            allow(callDetails)
            return
        }

        if (ContactChecker.isKnownContact(applicationContext, caller)) {
            Log.d(TAG, "Known contact $caller — allowing through")
            allow(callDetails)
            return
        }

        val contactRepo = ContactRuleRepository(AppDatabase.getInstance(applicationContext).contactRuleDao())
        if (contactRepo.isBlocked(caller)) {
            Log.d(TAG, "Blocked number $caller — rejecting")
            block(callDetails)
            return
        }
        if (contactRepo.isWhitelisted(caller)) {
            Log.d(TAG, "Whitelisted number $caller — allowing through")
            allow(callDetails)
            return
        }

        // Unknown caller — mute ringer and launch overlay for backend monitoring
        Log.d(TAG, "Unknown caller $caller — launching overlay")
        muteRinger()
        respondToCall(callDetails, CallResponse.Builder()
            .setDisallowCall(false)
            .setSilenceCall(true)
            .build())

        startActivity(Intent(this, ScreeningOverlayActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            putExtra(EXTRA_CALLER, caller)
        })
    }

    private fun allow(details: Call.Details) {
        respondToCall(details, CallResponse.Builder().setDisallowCall(false).build())
    }

    private fun block(details: Call.Details) {
        respondToCall(details, CallResponse.Builder()
            .setDisallowCall(true)
            .setRejectCall(true)
            .build())
    }

    private fun muteRinger() {
        try {
            val am = getSystemService(android.media.AudioManager::class.java)
            am?.adjustStreamVolume(android.media.AudioManager.STREAM_RING, android.media.AudioManager.ADJUST_MUTE, 0)
        } catch (_: Exception) {}
    }

    companion object {
        const val TAG = "ScreenerService"
        const val EXTRA_CALLER        = "caller_number"
        const val EXTRA_START_SESSION = "start_session"
    }
}
