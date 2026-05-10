package ai.phronetic.screener.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import ai.phronetic.screener.Config
import ai.phronetic.screener.data.db.AppDatabase
import ai.phronetic.screener.data.repository.CallHistoryRepository
import ai.phronetic.screener.data.repository.ContactRuleRepository
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class DashboardViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getInstance(application)
    private val callRepo = CallHistoryRepository(db.screenedCallDao())
    private val contactRepo = ContactRuleRepository(db.contactRuleDao())

    val isEnabled: Boolean
        get() = Config.isEnabled(getApplication())

    fun setEnabled(enabled: Boolean) {
        Config.setEnabled(getApplication(), enabled)
    }

    val stats: StateFlow<DashboardStats> = combine(
        callRepo.callCount,
        callRepo.spamCount,
        contactRepo.allRules
    ) { total, spam, rules ->
        DashboardStats(
            totalCalls = total,
            spamBlocked = spam,
            whitelisted = rules.count { it.type == ai.phronetic.screener.data.db.ContactRule.RuleType.WHITELIST },
            blocklisted = rules.count { it.type == ai.phronetic.screener.data.db.ContactRule.RuleType.BLOCKLIST }
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), DashboardStats())

    val recentCalls: StateFlow<List<ai.phronetic.screener.data.db.ScreenedCall>> =
        callRepo.allCalls.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun clearHistory() {
        viewModelScope.launch {
            callRepo.clearAll()
        }
    }
}

data class DashboardStats(
    val totalCalls: Int = 0,
    val spamBlocked: Int = 0,
    val whitelisted: Int = 0,
    val blocklisted: Int = 0
)
