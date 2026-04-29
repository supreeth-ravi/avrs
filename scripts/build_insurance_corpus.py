"""
Build a rich insurance corpus for Priya (HealthFirst Insurance).

Phrases are grouped by intent so it's easy to extend.
Run: python scripts/build_insurance_corpus.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from avrs.corpus import Corpus
from avrs.tts import get_engine
from avrs.config import RenderConfig

# ── Phrase library ─────────────────────────────────────────────────────────
PHRASES: list[str] = [

    # ── Greetings & openers ─────────────────────────────────────────────
    "Hello, thank you for calling HealthFirst Insurance.",
    "Welcome to HealthFirst Insurance.",
    "I am Priya, your insurance assistant.",
    "How may I assist you today?",
    "Good morning, how may I assist you today?",
    "Good afternoon, how may I assist you today?",
    "Good evening, how may I assist you today?",
    "Welcome to HealthFirst Insurance. I am Priya and I will assist you today.",
    "Thank you for calling HealthFirst Insurance.",

    # ── Acknowledgements & transitions ─────────────────────────────────
    "Of course, let me check that for you.",
    "Sure, let me pull that up right away.",
    "One moment please.",
    "Please give me a moment to check your details.",
    "Please stay on the line.",
    "Let me pull up your policy information right away.",
    "I can see your account here.",
    "I have looked up your details.",
    "I can see that on your account.",
    "Let me look into that for you.",
    "I will be happy to help you with that.",
    "I understand your concern.",
    "I appreciate your patience.",
    "Thank you for your patience.",
    "Absolutely, I can help you with that.",
    "Great question. Let me check that.",
    "I have your policy details in front of me.",

    # ── Policy status ────────────────────────────────────────────────────
    "Your policy is currently active.",
    "Your policy is active and in good standing.",
    "Your health insurance policy is currently active.",
    "Your motor insurance policy is currently active.",
    "Your vehicle insurance is active.",
    "Your coverage is valid.",
    "Your policy is due for renewal.",
    "Your policy has expired.",
    "Your policy has been cancelled.",
    "Your policy has been renewed successfully.",
    "Your policy is valid and up to date.",
    "Your policy is active and will renew automatically.",
    "Your health policy covers you and your family.",
    "Your policy provides cashless treatment at network hospitals.",

    # ── Premium & payment ────────────────────────────────────────────────
    "Your premium payment was successful.",
    "Your premium has been processed.",
    "Your premium is overdue.",
    "Your premium payment is pending.",
    "Would you like to set up automatic payments?",
    "You can pay your premium online through our app or website.",
    "Your premium will be auto-debited on the due date.",
    "We have received your premium payment.",
    "A renewal confirmation will be sent to your registered email.",
    "Would you like to renew your policy today?",
    "Your policy will expire soon. I recommend renewing it at the earliest.",
    "You can renew your policy through our app, website, or by calling us.",

    # ── Claim status ─────────────────────────────────────────────────────
    "Your claim is currently under review.",
    "Your claim has been approved.",
    "Your claim has been rejected.",
    "Your claim has been settled.",
    "Your claim has been submitted successfully.",
    "We have received your claim documents.",
    "Your claim is being processed.",
    "Your claim is under review and will be resolved soon.",
    "Our claims team is reviewing your request.",
    "You can expect a decision within five to seven business days.",
    "You will receive an update on your claim via SMS and email.",
    "Your claim will be settled directly with the hospital.",
    "The claim amount will be credited to your registered bank account.",
    "I have raised your claim and assigned it to our team.",
    "Let me connect you with our claims specialist.",
    "Your reimbursement will be processed within seven working days.",

    # ── Documents & submission ───────────────────────────────────────────
    "Please submit your documents to process your claim.",
    "We require your discharge summary and bills for your claim.",
    "Please upload the required documents through our app.",
    "You will need your hospital bills, discharge summary, and prescription.",
    "For a health claim, please submit the original bills and discharge summary.",
    "For a motor claim, please submit the repair estimate and FIR copy.",
    "Our team will verify your documents within two business days.",
    "Your documents have been received and are under review.",

    # ── Network hospitals & cashless ────────────────────────────────────
    "Apollo Hospital is part of our network hospitals.",
    "You are eligible for cashless treatment at this hospital.",
    "This hospital is in our network and cashless treatment is available.",
    "You can find the nearest network hospital on our app.",
    "We have over eight thousand five hundred network hospitals across India.",
    "To avail cashless treatment, please show your insurance card at the hospital.",
    "Our cashless facility is available at all network hospitals.",
    "Please inform the hospital that you have HealthFirst Insurance.",

    # ── Escalation & specialist ──────────────────────────────────────────
    "I will escalate this to our specialist team.",
    "I am connecting you to a senior specialist who can assist you further.",
    "Our specialist team will call you back within twenty four hours.",
    "I have raised a service request on your behalf.",
    "I apologize for the inconvenience.",
    "I sincerely apologize for the inconvenience caused.",
    "We are working to resolve this at the earliest.",

    # ── Notifications & confirmations ────────────────────────────────────
    "Your policy document has been sent to your registered email.",
    "We will send you a confirmation via SMS.",
    "You will receive an SMS and email confirmation shortly.",
    "A copy of your policy has been emailed to you.",

    # ── Closings ─────────────────────────────────────────────────────────
    "Is there anything else I can assist you with?",
    "Is there anything else I can help you with today?",
    "It was a pleasure assisting you today.",
    "Thank you for choosing HealthFirst Insurance.",
    "We value your trust in HealthFirst Insurance.",
    "We appreciate your business.",
    "Have a wonderful day.",
    "Take care, goodbye.",
    "Thank you for calling. Goodbye.",
    "Stay safe and take care.",
]


def main() -> None:
    corpus_dir = os.path.join(os.path.dirname(__file__), "..", "corpus", "insurance")
    config = RenderConfig(
        tts_model="kokoro",
        corpus_dir=corpus_dir,
        cache_dir=os.path.join(os.path.dirname(__file__), "..", "cache", "insurance"),
        voice_id="priya",
        sr=22050,
    )

    engine = get_engine(config.tts_model)
    corpus = Corpus(corpus_dir, engine, config.voice_id)

    already = set(corpus._index.keys())
    new_phrases = [p for p in PHRASES if p.strip().lower() not in already]
    skipped = len(PHRASES) - len(new_phrases)

    print(f"Corpus: {len(already)} existing | {len(new_phrases)} new | {skipped} already present")
    if not new_phrases:
        print("Nothing to add.")
        return

    print(f"Synthesising {len(new_phrases)} phrases with Kokoro...")
    for i, phrase in enumerate(new_phrases, 1):
        try:
            corpus.build_from_phrases([phrase], ref_audio=None, sr=config.sr)
            print(f"  [{i:3d}/{len(new_phrases)}] ✓  {phrase}")
        except Exception as e:
            print(f"  [{i:3d}/{len(new_phrases)}] ✗  {phrase}  ({e})")

    total = len(corpus._index)
    print(f"\nDone. Corpus now has {total} phrases.")


if __name__ == "__main__":
    main()
