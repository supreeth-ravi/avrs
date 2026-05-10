package ai.phronetic.screener.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import ai.phronetic.screener.data.db.AppDatabase
import ai.phronetic.screener.data.db.ContactRule
import ai.phronetic.screener.data.repository.ContactRuleRepository
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class ContactsViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getInstance(application)
    private val repository = ContactRuleRepository(db.contactRuleDao())

    val whitelist: StateFlow<List<ContactRule>> =
        repository.whitelist.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val blocklist: StateFlow<List<ContactRule>> =
        repository.blocklist.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun addToWhitelist(number: String, name: String? = null) {
        viewModelScope.launch {
            repository.addRule(
                ContactRule(phoneNumber = number, name = name, type = ContactRule.RuleType.WHITELIST)
            )
        }
    }

    fun addToBlocklist(number: String, name: String? = null) {
        viewModelScope.launch {
            repository.addRule(
                ContactRule(phoneNumber = number, name = name, type = ContactRule.RuleType.BLOCKLIST)
            )
        }
    }

    fun removeRule(rule: ContactRule) {
        viewModelScope.launch { repository.removeRule(rule) }
    }
}
