package ai.phronetic.screener.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import ai.phronetic.screener.data.db.AppDatabase
import ai.phronetic.screener.data.db.ScreenedCall
import ai.phronetic.screener.data.repository.CallHistoryRepository
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

class HistoryViewModel(application: Application) : AndroidViewModel(application) {

    private val db = AppDatabase.getInstance(application)
    private val repository = CallHistoryRepository(db.screenedCallDao())

    val calls: StateFlow<List<ScreenedCall>> =
        repository.allCalls.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val spamCalls: StateFlow<List<ScreenedCall>> =
        repository.spamCalls.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun deleteCall(call: ScreenedCall) {
        viewModelScope.launch { repository.delete(call) }
    }

    fun clearAll() {
        viewModelScope.launch { repository.clearAll() }
    }
}
