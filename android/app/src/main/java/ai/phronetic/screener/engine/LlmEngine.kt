package ai.phronetic.screener.engine

import android.util.Log
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class LlmEngine(private val apiKey: String) : ScreeningEngine {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    private val systemPrompt = """
You are a polite, concise AI call screening assistant answering on behalf of someone who cannot take the call right now.
Your job: find out WHO is calling and WHY, in as few exchanges as possible.

RULES:
- Speak naturally, like a real human assistant — warm but efficient.
- Keep each response to 1–2 short sentences. This is a live phone call.
- Never say you are an AI unless directly asked.
- After your spoken text, on new lines write INTENT and ACTION tags.

INTENT options (pick one):
  spam       — telemarketer, robocall, sales pitch
  delivery   — courier, food delivery, package
  work       — office, client, professional matter
  personal   — friend, family, personal topic
  emergency  — urgent, accident, hospital, help needed
  unknown    — cannot determine yet

ACTION options (pick one):
  continue   — keep the conversation going
  end_call   — politely close the call (enough info gathered, or spam)
  flag_urgent — alert the phone owner immediately (emergency)

OUTPUT FORMAT (strictly follow this every time):
<your spoken sentence(s)>
INTENT: <value>
ACTION: <value>

EXAMPLE TURN 1:
Hi there, I'm managing their calls right now. May I ask who's calling?
INTENT: unknown
ACTION: continue

EXAMPLE TURN 2 (after caller says "I'm from Amazon delivery"):
Got it! What time are you expecting to arrive?
INTENT: delivery
ACTION: continue
""".trimIndent()

    override fun respond(history: List<Turn>): ScreeningResult {
        if (history.isEmpty()) {
            return ScreeningResult(
                spokenText = "Hi there, I'm managing their calls right now. May I ask who's calling and what it's regarding?",
                intent = "unknown",
                action = "continue",
                corpusKey = null,
            )
        }

        return try {
            val messages = buildMessages(history)
            Log.d(TAG, "[LLM] Sending ${messages.length()} messages to Claude")
            val raw = callClaude(messages)
            Log.d(TAG, "[LLM] Raw response: $raw")
            parse(raw)
        } catch (e: Exception) {
            Log.e(TAG, "[LLM] API call failed: ${e.message}")
            ScreeningResult(
                spokenText = "Sorry, could you say that again?",
                intent = "unknown",
                action = "continue",
                corpusKey = null,
            )
        }
    }

    private fun buildMessages(history: List<Turn>): JSONArray {
        val msgs = JSONArray()
        for (turn in history) {
            msgs.put(JSONObject().apply {
                put("role", if (turn.role == "caller") "user" else "assistant")
                put("content", turn.text)
            })
        }
        return msgs
    }

    private fun callClaude(messages: JSONArray): String {
        val body = JSONObject().apply {
            put("model", "claude-haiku-4-5-20251001")
            put("max_tokens", 200)
            put("system", systemPrompt)
            put("messages", messages)
        }

        val request = Request.Builder()
            .url("https://api.anthropic.com/v1/messages")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .header("x-api-key", apiKey)
            .header("anthropic-version", "2023-06-01")
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val err = response.body?.string() ?: ""
                throw RuntimeException("Claude API ${response.code}: $err")
            }
            val json = JSONObject(response.body!!.string())
            return json.getJSONArray("content").getJSONObject(0).getString("text")
        }
    }

    private fun parse(raw: String): ScreeningResult {
        val intentMatch = Regex("""INTENT:\s*(\w+)""", RegexOption.IGNORE_CASE).find(raw)
        val actionMatch = Regex("""ACTION:\s*(\w+)""", RegexOption.IGNORE_CASE).find(raw)
        val spoken = raw
            .replace(Regex("""INTENT:\s*\w+""", RegexOption.IGNORE_CASE), "")
            .replace(Regex("""ACTION:\s*\w+""", RegexOption.IGNORE_CASE), "")
            .trim()
        val intent = intentMatch?.groupValues?.getOrNull(1)?.lowercase() ?: "unknown"
        val action = actionMatch?.groupValues?.getOrNull(1)?.lowercase() ?: "continue"
        Log.d(TAG, "[LLM] Parsed → spoken='$spoken' intent=$intent action=$action")
        return ScreeningResult(spokenText = spoken, intent = intent, action = action, corpusKey = null)
    }

    companion object {
        private const val TAG = "LlmEngine"
    }
}
