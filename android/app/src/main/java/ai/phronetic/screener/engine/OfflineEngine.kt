package ai.phronetic.screener.engine

/**
 * Fully offline screening engine.
 * No network, no API key, no models to download.
 *
 * Uses keyword matching on the caller's speech to classify intent,
 * then picks from a fixed set of pre-recorded response phrases.
 * All response audio is served from corpus WAV files bundled in assets/.
 */
class OfflineEngine : ScreeningEngine {

    override fun respond(history: List<Turn>): ScreeningResult {
        val callerTurns = history.filter { it.role == "caller" }
        val lastCallerText = callerTurns.lastOrNull()?.text?.lowercase() ?: ""
        val turnCount = callerTurns.size

        // Opening — no caller speech yet
        if (turnCount == 0) {
            return ScreeningResult(
                spokenText = "Hello, I'm handling calls for them right now. May I know who's calling?",
                intent = "unknown",
                action = "continue",
                corpusKey = "screener_greeting",
            )
        }

        val intent = classifyIntent(lastCallerText)

        return when (intent) {
            "spam" -> ScreeningResult(
                spokenText = "Thank you, but we're not interested. Have a good day.",
                intent = "spam",
                action = "end_call",
                corpusKey = "screener_not_interested",
            )
            "delivery" -> {
                if (turnCount == 1) {
                    ScreeningResult(
                        spokenText = "Got it, thank you. I'll let them know you're here. What's the expected delivery time?",
                        intent = "delivery",
                        action = "continue",
                        corpusKey = "screener_delivery_eta",
                    )
                } else {
                    ScreeningResult(
                        spokenText = "Understood. I'll pass that along. Thank you.",
                        intent = "delivery",
                        action = "end_call",
                        corpusKey = "screener_pass_along",
                    )
                }
            }
            "emergency" -> ScreeningResult(
                spokenText = "This sounds urgent. Let me get them for you right away.",
                intent = "emergency",
                action = "flag_urgent",
                corpusKey = "screener_urgent",
            )
            "work", "personal" -> {
                if (turnCount == 1) {
                    ScreeningResult(
                        spokenText = "I see. Could you briefly tell me what this is regarding?",
                        intent = intent,
                        action = "continue",
                        corpusKey = "screener_ask_purpose",
                    )
                } else {
                    ScreeningResult(
                        spokenText = "Got it. I'll let them know you called. They'll get back to you shortly.",
                        intent = intent,
                        action = "end_call",
                        corpusKey = "screener_will_call_back",
                    )
                }
            }
            else -> {
                // Unknown — ask once more, then end
                if (turnCount <= 2) {
                    ScreeningResult(
                        spokenText = "Sorry, could you repeat that? Who's calling and what's this regarding?",
                        intent = "unknown",
                        action = "continue",
                        corpusKey = "screener_repeat",
                    )
                } else {
                    ScreeningResult(
                        spokenText = "I'll let them know someone called. Have a good day.",
                        intent = "unknown",
                        action = "end_call",
                        corpusKey = "screener_goodbye",
                    )
                }
            }
        }
    }

    private fun classifyIntent(text: String): String {
        if (SPAM_KEYWORDS.any { text.contains(it) })      return "spam"
        if (DELIVERY_KEYWORDS.any { text.contains(it) })  return "delivery"
        if (EMERGENCY_KEYWORDS.any { text.contains(it) }) return "emergency"
        if (WORK_KEYWORDS.any { text.contains(it) })      return "work"
        if (PERSONAL_KEYWORDS.any { text.contains(it) })  return "personal"
        return "unknown"
    }

    companion object {
        private val SPAM_KEYWORDS = listOf(
            "insurance", "loan", "offer", "discount", "free", "congratulations",
            "won", "prize", "investment", "mutual fund", "credit card offer",
            "emi", "scheme", "apply now", "limited time", "promotional",
        )
        private val DELIVERY_KEYWORDS = listOf(
            "delivery", "deliver", "courier", "package", "parcel", "order",
            "swiggy", "zomato", "amazon", "flipkart", "dunzo", "blinkit",
            "zepto", "instamart", "food", "otp",
        )
        private val EMERGENCY_KEYWORDS = listOf(
            "emergency", "urgent", "accident", "hospital", "ambulance",
            "police", "fire", "help", "critical", "immediately",
        )
        private val WORK_KEYWORDS = listOf(
            "office", "company", "colleague", "manager", "meeting", "work",
            "business", "client", "project", "interview", "hr", "hiring",
        )
        private val PERSONAL_KEYWORDS = listOf(
            "friend", "family", "brother", "sister", "mother", "father",
            "mom", "dad", "uncle", "aunt", "cousin", "neighbour",
        )
    }
}
