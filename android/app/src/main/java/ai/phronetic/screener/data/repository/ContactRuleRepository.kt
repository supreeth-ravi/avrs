package ai.phronetic.screener.data.repository

import ai.phronetic.screener.data.db.ContactRule
import ai.phronetic.screener.data.db.ContactRuleDao
import kotlinx.coroutines.flow.Flow

class ContactRuleRepository(private val dao: ContactRuleDao) {

    val whitelist: Flow<List<ContactRule>> = dao.getWhitelist()
    val blocklist: Flow<List<ContactRule>> = dao.getBlocklist()
    val allRules: Flow<List<ContactRule>> = dao.getAll()

    suspend fun addRule(rule: ContactRule): Long = dao.insert(rule)

    suspend fun removeRule(rule: ContactRule) = dao.delete(rule)

    suspend fun removeByNumber(number: String) = dao.deleteByNumber(number)

    fun isWhitelisted(number: String): Boolean = dao.isWhitelisted(number)

    fun isBlocked(number: String): Boolean = dao.isBlocked(number)

    suspend fun getByNumber(number: String): ContactRule? = dao.getByNumber(number)
}
