"""Prompt 4.5 — spoken challenge-response issue/verify flow."""
from voice.challenge import ChallengeManager


def test_issue_then_verify_success():
    m = ChallengeManager()
    ch = m.issue("owner")
    assert ch["phrase"] and ch["challenge_id"]
    r = m.verify(owner="owner", challenge_id=ch["challenge_id"],
                 spoken_text=ch["phrase"], biometric_ok=True)
    assert r.ok


def test_wrong_phrase_fails():
    m = ChallengeManager()
    ch = m.issue("owner")
    r = m.verify(owner="owner", challenge_id=ch["challenge_id"],
                 spoken_text="totally different words", biometric_ok=True)
    assert not r.ok and "match" in r.reason


def test_biometric_must_pass():
    m = ChallengeManager()
    ch = m.issue("owner")
    r = m.verify(owner="owner", challenge_id=ch["challenge_id"],
                 spoken_text=ch["phrase"], biometric_ok=False)
    assert not r.ok and "biometric" in r.reason


def test_expired_challenge_fails():
    clock = [1000.0]
    m = ChallengeManager(ttl_seconds=30, now=lambda: clock[0])
    ch = m.issue("owner")
    clock[0] += 31
    r = m.verify(owner="owner", challenge_id=ch["challenge_id"],
                 spoken_text=ch["phrase"], biometric_ok=True)
    assert not r.ok and "expired" in r.reason


def test_replay_is_rejected():
    m = ChallengeManager()
    ch = m.issue("owner")
    assert m.verify(owner="owner", challenge_id=ch["challenge_id"],
                    spoken_text=ch["phrase"], biometric_ok=True).ok
    # second use of the same challenge id is consumed
    again = m.verify(owner="owner", challenge_id=ch["challenge_id"],
                     spoken_text=ch["phrase"], biometric_ok=True)
    assert not again.ok


def test_normalization_ignores_case_and_punctuation():
    m = ChallengeManager()
    ch = m.issue("owner")
    spoken = ch["phrase"].upper() + "!!"
    assert m.verify(owner="owner", challenge_id=ch["challenge_id"],
                    spoken_text=spoken, biometric_ok=True).ok


def test_other_owner_cannot_verify():
    m = ChallengeManager()
    ch = m.issue("alice")
    r = m.verify(owner="bob", challenge_id=ch["challenge_id"],
                 spoken_text=ch["phrase"], biometric_ok=True)
    assert not r.ok
