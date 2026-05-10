package ai.phronetic.screener

import android.content.Context
import android.provider.ContactsContract

object ContactChecker {

    /** Returns true if [number] matches any saved contact on the device. */
    fun isKnownContact(context: Context, number: String): Boolean {
        val uri = android.net.Uri.withAppendedPath(
            ContactsContract.PhoneLookup.CONTENT_FILTER_URI,
            android.net.Uri.encode(number)
        )
        return try {
            context.contentResolver.query(uri, arrayOf(ContactsContract.PhoneLookup._ID), null, null, null)
                ?.use { cursor -> cursor.count > 0 } ?: false
        } catch (e: Exception) {
            false
        }
    }
}
