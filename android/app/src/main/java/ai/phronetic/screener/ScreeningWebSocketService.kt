package ai.phronetic.screener

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Binder
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Foreground service that maintains a WebSocket connection to the AVRS backend.
 *
 * Receives live call-screening events (transcript, intent, agent speech, call end)
 * from the backend and broadcasts them to the UI.  Forwards user actions
 * (join / block / message / typed_message) back to the backend.
 *
 * This replaces the old ScreeningSession which tried to do PSTN audio injection
 * locally (impossible due to hardware modem AEC).  All audio processing now
 * happens server-side via Exotel SIP/WebSocket.
 */
class ScreeningWebSocketService : Service() {

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .build()

    private var currentCallSid: String? = null
    private var isConnected = false

    private val localReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                ACTION_SEND -> {
                    val type = intent.getStringExtra("type") ?: return
                    val payload = intent.getStringExtra("payload") ?: return
                    sendToServer(type, payload)
                }
                ACTION_DISCONNECT -> disconnect()
            }
        }
    }

    inner class LocalBinder : Binder() {
        fun getService(): ScreeningWebSocketService = this@ScreeningWebSocketService
    }

    override fun onCreate() {
        super.onCreate()
        registerReceiver(localReceiver, IntentFilter().apply {
            addAction(ACTION_SEND)
            addAction(ACTION_DISCONNECT)
        }, Context.RECEIVER_NOT_EXPORTED)
    }

    override fun onBind(intent: Intent?): IBinder = LocalBinder()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val callerNumber = intent?.getStringExtra(EXTRA_CALLER) ?: "Unknown"
        currentCallSid = intent?.getStringExtra(EXTRA_CALL_SID)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIF_ID, buildNotification(callerNumber),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIF_ID, buildNotification(callerNumber))
        }

        connect(callerNumber)
        return START_NOT_STICKY
    }

    private fun connect(callerNumber: String) {
        val serverUrl = Config.SERVER_URL
            .replace("https://", "wss://")
            .replace("http://", "ws://")
            .trimEnd('/')

        val token = Config.getAuthToken(this)
        val wsUrl = "$serverUrl/ws/screen?token=$token"
        Log.d(TAG, "[WS] Connecting to $wsUrl")

        val request = Request.Builder().url(wsUrl).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                Log.d(TAG, "[WS] Connected")
                isConnected = true
                broadcastLocal(EVENT_CONNECTED, null)
            }

            override fun onMessage(ws: WebSocket, text: String) {
                handleServerMessage(text)
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "[WS] Closing: $code $reason")
                ws.close(code, reason)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "[WS] Closed: $code $reason")
                isConnected = false
                broadcastLocal(EVENT_DISCONNECTED, null)
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                Log.e(TAG, "[WS] Failure: ${t.message}")
                isConnected = false
                broadcastLocal(EVENT_DISCONNECTED, t.message)
                // Auto-reconnect after delay
                scope.launch {
                    delay(5000)
                    if (!isConnected) connect(callerNumber)
                }
            }
        })
    }

    private fun handleServerMessage(text: String) {
        try {
            val json = JSONObject(text)
            val type = json.getString("type")
            Log.d(TAG, "[WS] << $type")

            when (type) {
                "call.started" -> {
                    currentCallSid = json.optString("call_sid", currentCallSid)
                    broadcastLocal(EVENT_CALL_STARTED, text)
                }
                "transcript.final" -> broadcastLocal(EVENT_TRANSCRIPT, text)
                "intent" -> broadcastLocal(EVENT_INTENT, text)
                "agent.speaking" -> broadcastLocal(EVENT_AGENT_SPEAKING, text)
                "call.end" -> {
                    broadcastLocal(EVENT_CALL_END, text)
                    stopSelf()
                }
                "ready" -> broadcastLocal(EVENT_READY, text)
                "error" -> broadcastLocal(EVENT_ERROR, text)
            }
        } catch (e: Exception) {
            Log.w(TAG, "[WS] Parse error: $e")
        }
    }

    private fun sendToServer(type: String, payload: String) {
        if (!isConnected) {
            Log.w(TAG, "[WS] Not connected, cannot send $type")
            return
        }
        try {
            val json = JSONObject().apply {
                put("type", type)
                when (type) {
                    "action" -> {
                        val data = JSONObject(payload)
                        put("action", data.getString("action"))
                        put("call_sid", data.optString("call_sid", currentCallSid))
                        if (data.has("text")) put("text", data.getString("text"))
                    }
                    else -> put("payload", payload)
                }
            }
            webSocket?.send(json.toString())
            Log.d(TAG, "[WS] >> $type")
        } catch (e: Exception) {
            Log.e(TAG, "[WS] Send error: $e")
        }
    }

    private fun disconnect() {
        Log.d(TAG, "[WS] Disconnecting")
        webSocket?.close(1000, "user_disconnect")
        webSocket = null
        isConnected = false
        stopSelf()
    }

    private fun broadcastLocal(action: String, payload: String?) {
        sendBroadcast(Intent(action).apply {
            payload?.let { putExtra("payload", it) }
            putExtra("call_sid", currentCallSid)
        })
    }

    private fun buildNotification(caller: String): Notification {
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(
            NotificationChannel(NOTIF_CHANNEL, "Call Screening", NotificationManager.IMPORTANCE_LOW)
        )
        return Notification.Builder(this, NOTIF_CHANNEL)
            .setContentTitle("Screening call from $caller")
            .setContentText("AI is handling the call via Pickr")
            .setSmallIcon(android.R.drawable.ic_menu_call)
            .setOngoing(true)
            .build()
    }

    override fun onDestroy() {
        unregisterReceiver(localReceiver)
        webSocket?.close(1000, "service_destroyed")
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        const val TAG = "ScreeningWebSocketService"
        const val EXTRA_CALLER = "caller_number"
        const val EXTRA_CALL_SID = "call_sid"

        // Local broadcast actions
        const val ACTION_SEND = "ai.phronetic.screener.WS_SEND"
        const val ACTION_DISCONNECT = "ai.phronetic.screener.WS_DISCONNECT"

        const val EVENT_CONNECTED = "ai.phronetic.screener.EVENT_CONNECTED"
        const val EVENT_DISCONNECTED = "ai.phronetic.screener.EVENT_DISCONNECTED"
        const val EVENT_READY = "ai.phronetic.screener.EVENT_READY"
        const val EVENT_CALL_STARTED = "ai.phronetic.screener.EVENT_CALL_STARTED"
        const val EVENT_TRANSCRIPT = "ai.phronetic.screener.EVENT_TRANSCRIPT"
        const val EVENT_INTENT = "ai.phronetic.screener.EVENT_INTENT"
        const val EVENT_AGENT_SPEAKING = "ai.phronetic.screener.EVENT_AGENT_SPEAKING"
        const val EVENT_CALL_END = "ai.phronetic.screener.EVENT_CALL_END"
        const val EVENT_ERROR = "ai.phronetic.screener.EVENT_ERROR"

        private const val NOTIF_ID = 2
        private const val NOTIF_CHANNEL = "screening_ws"

        fun start(context: Context, callerNumber: String, callSid: String? = null) {
            context.startForegroundService(
                Intent(context, ScreeningWebSocketService::class.java).apply {
                    putExtra(EXTRA_CALLER, callerNumber)
                    callSid?.let { putExtra(EXTRA_CALL_SID, it) }
                }
            )
        }

        fun sendAction(context: Context, action: String, callSid: String?, text: String? = null) {
            val payload = JSONObject().apply {
                put("action", action)
                callSid?.let { put("call_sid", it) }
                text?.let { put("text", it) }
            }.toString()
            context.sendBroadcast(Intent(ACTION_SEND).apply {
                putExtra("type", "action")
                putExtra("payload", payload)
            })
        }
    }
}
