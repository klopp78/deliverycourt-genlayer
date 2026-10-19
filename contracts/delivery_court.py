# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

"""Challengeable, source-bound rulings for public service delivery disputes."""

from genlayer import *
import hashlib
import json
import typing

SNAPSHOT_LIMIT = 3200


class DeliveryCourt(gl.Contract):
    claim_count: u64
    latest_claim_id: str
    latest_review_id: str
    latest_challenge_id: str
    latest_verdict_id: str
    claims: TreeMap[str, str]
    reviews: TreeMap[str, str]
    challenges: TreeMap[str, str]
    verdicts: TreeMap[str, str]
    claim_ids: DynArray[str]

    def __init__(self):
        self.claim_count = u64(0)
        self.latest_claim_id = ""
        self.latest_review_id = ""
        self.latest_challenge_id = ""
        self.latest_verdict_id = ""

    @gl.public.view
    def get_claim(self, claim_id: str) -> str:
        return self.claims.get(claim_id.strip(), "")

    @gl.public.view
    def get_review(self, review_id: str) -> str:
        return self.reviews.get(review_id.strip(), "")

    @gl.public.view
    def get_challenge(self, challenge_id: str) -> str:
        return self.challenges.get(challenge_id.strip(), "")

    @gl.public.view
    def get_verdict(self, verdict_id: str) -> str:
        return self.verdicts.get(verdict_id.strip(), "")

    @gl.public.view
    def list_claim_ids(self) -> str:
        return _canonical_json([claim_id for claim_id in self.claim_ids])

    @gl.public.write
    def register_delivery_claim(self, service_reference: str, promised_delivery: str, deadline_utc: str, buyer_evidence_url: str, provider_evidence_url: str, challenge_window_seconds: str) -> str:
        reference = _clean(service_reference, 100, "service_reference_required")
        promise = _clean(promised_delivery, 260, "promised_delivery_required")
        deadline = _clean(deadline_utc, 80, "deadline_required")
        window = _window(challenge_window_seconds)
        sources = [_source("buyer_evidence", buyer_evidence_url), _source("provider_evidence", provider_evidence_url)]

        def leader_fn():
            return _canonical_json(_baseline(reference, promise, deadline, _render_all(sources)))

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                return _canonical_json(json.loads(leader_result.value)) == _canonical_json(_baseline(reference, promise, deadline, _render_all(sources)))
            except Exception:
                return False

        baseline = json.loads(gl.vm.run_nondet_unsafe(leader_fn, validator_fn))
        claim_id = "dlv_" + _sha256(reference + "|" + promise + "|" + baseline["baseline_hash"])[:20]
        if self.claims.get(claim_id, ""):
            raise Exception("delivery_claim_already_registered")
        claim = {"id": claim_id, "service_reference": reference, "promised_delivery": promise, "deadline_utc": deadline, "baseline_evidence": baseline["snapshots"], "snapshot_commitments": baseline["snapshot_commitments"], "baseline_hash": baseline["baseline_hash"], "challenge_window_seconds": window, "status": "open", "review_id": "", "challenge_id": "", "verdict_id": "", "created_at": _now()}
        self.claims[claim_id] = _canonical_json(claim)
        self.claim_ids.append(claim_id)
        self.claim_count = u64(int(self.claim_count) + 1)
        self.latest_claim_id = claim_id
        return claim_id

    @gl.public.write
    def assess_delivery(self, claim_id: str, delivery_evidence_url: str) -> str:
        claim = _load(self.claims, claim_id, "unknown_delivery_claim")
        if claim["status"] != "open":
            raise Exception("claim_not_open_for_assessment")
        source = _source("delivery_evidence", delivery_evidence_url)

        def leader_fn():
            return _canonical_json(_review(claim, _render_all([source])[0]))

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                return _same_decision(json.loads(leader_result.value), _review(claim, _render_all([source])[0]), "review")
            except Exception:
                return False

        result = json.loads(gl.vm.run_nondet_unsafe(leader_fn, validator_fn))
        review_id = "rev_" + _sha256(claim["id"] + "|" + result["review_hash"])[:20]
        if self.reviews.get(review_id, ""):
            raise Exception("delivery_review_already_exists")
        review = {"id": review_id, "claim_id": claim["id"], "outcome": result["outcome"], "confidence": result["confidence"], "summary": result["summary"], "delivery_evidence": result["delivery_evidence"], "baseline_hash": claim["baseline_hash"], "evidence_commitment": result["evidence_commitment"], "review_hash": result["review_hash"], "created_at": _now()}
        claim["status"] = "reviewed"
        claim["review_id"] = review_id
        claim["challenge_deadline"] = _now() + int(claim["challenge_window_seconds"])
        self.claims[claim["id"]] = _canonical_json(claim)
        self.reviews[review_id] = _canonical_json(review)
        self.latest_review_id = review_id
        return review_id

    @gl.public.write
    def challenge_delivery_review(self, claim_id: str, review_id: str, counterevidence_url: str) -> str:
        claim = _load(self.claims, claim_id, "unknown_delivery_claim")
        if claim["status"] != "reviewed" or claim["review_id"] != review_id.strip():
            raise Exception("review_not_challengeable")
        if _now() > int(claim["challenge_deadline"]):
            raise Exception("challenge_window_closed")
        review = _load(self.reviews, review_id, "unknown_delivery_review")
        source = _source("counterevidence", counterevidence_url)

        def leader_fn():
            return _canonical_json(_render_all([source])[0])

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                return _canonical_json(json.loads(leader_result.value)) == _canonical_json(_render_all([source])[0])
            except Exception:
                return False

        snapshot = json.loads(gl.vm.run_nondet_unsafe(leader_fn, validator_fn))
        challenge_id = "dch_" + _sha256(claim["id"] + "|" + review["review_hash"] + "|" + snapshot["snapshot_hash"])[:20]
        if self.challenges.get(challenge_id, ""):
            raise Exception("delivery_challenge_already_exists")
        challenge = {"id": challenge_id, "claim_id": claim["id"], "review_id": review["id"], "counterevidence": snapshot, "baseline_hash": claim["baseline_hash"], "status": "pending_resolution", "created_at": _now()}
        claim["status"] = "challenged"
        claim["challenge_id"] = challenge_id
        self.claims[claim["id"]] = _canonical_json(claim)
        self.challenges[challenge_id] = _canonical_json(challenge)
        self.latest_challenge_id = challenge_id
        return challenge_id

    @gl.public.write
    def resolve_delivery_challenge(self, claim_id: str, challenge_id: str) -> str:
        claim = _load(self.claims, claim_id, "unknown_delivery_claim")
        if claim["status"] != "challenged" or claim["challenge_id"] != challenge_id.strip():
            raise Exception("challenge_not_pending")
        review = _load(self.reviews, claim["review_id"], "unknown_delivery_review")
        challenge = _load(self.challenges, challenge_id, "unknown_delivery_challenge")
        if review["baseline_hash"] != claim["baseline_hash"] or challenge["baseline_hash"] != claim["baseline_hash"]:
            raise Exception("snapshot_binding_mismatch")

        def leader_fn():
            return _canonical_json(_resolution(claim, review, challenge))

        def validator_fn(leader_result) -> bool:
            if not isinstance(leader_result, gl.vm.Return):
                return False
            try:
                return _same_decision(json.loads(leader_result.value), _resolution(claim, review, challenge), "resolution")
            except Exception:
                return False

        result = json.loads(gl.vm.run_nondet_unsafe(leader_fn, validator_fn))
        challenge["status"] = "resolved"
        challenge["resolution_outcome"] = result["outcome"]
        challenge["resolution_hash"] = result["resolution_hash"]
        claim["status"] = "resolved"
        self.challenges[challenge_id] = _canonical_json(challenge)
        self.claims[claim["id"]] = _canonical_json(claim)
        return challenge_id

    @gl.public.write
    def finalize_delivery_verdict(self, claim_id: str) -> str:
        claim = _load(self.claims, claim_id, "unknown_delivery_claim")
        if claim["status"] == "reviewed" and _now() <= int(claim["challenge_deadline"]):
            raise Exception("challenge_window_still_open")
        if claim["status"] not in ["reviewed", "resolved"]:
            raise Exception("claim_not_finalizable")
        review = _load(self.reviews, claim["review_id"], "unknown_delivery_review")
        outcome, resolution_hash = review["outcome"], ""
        if claim["status"] == "resolved":
            challenge = _load(self.challenges, claim["challenge_id"], "unknown_delivery_challenge")
            outcome, resolution_hash = challenge["resolution_outcome"], challenge["resolution_hash"]
        verdict_id = "dvr_" + _sha256(claim["id"] + "|" + review["review_hash"] + "|" + resolution_hash + "|" + outcome)[:20]
        if self.verdicts.get(verdict_id, ""):
            raise Exception("delivery_verdict_already_finalized")
        verdict = {"id": verdict_id, "claim_id": claim["id"], "review_id": review["id"], "challenge_id": claim["challenge_id"], "outcome": outcome, "review_hash": review["review_hash"], "resolution_hash": resolution_hash, "baseline_hash": claim["baseline_hash"], "finalized_at": _now()}
        claim["status"] = "finalized"
        claim["verdict_id"] = verdict_id
        self.claims[claim["id"]] = _canonical_json(claim)
        self.verdicts[verdict_id] = _canonical_json(verdict)
        self.latest_verdict_id = verdict_id
        return verdict_id


def _baseline(reference: str, promise: str, deadline: str, snapshots: typing.Sequence[dict]) -> dict:
    commitments = _commitments(snapshots)
    return {"snapshots": snapshots, "snapshot_commitments": commitments, "baseline_hash": _sha256(_canonical_json({"service_reference": reference, "promised_delivery": promise, "deadline_utc": deadline, "snapshot_commitments": commitments}))}


def _review(claim: dict, delivery_snapshot: dict) -> dict:
    evidence = list(claim["baseline_evidence"]) + [delivery_snapshot]
    commitment = _evidence_commitment(claim["baseline_hash"], evidence)
    decision = _decision(_judge("delivery_review", {"promise": claim["promised_delivery"], "deadline_utc": claim["deadline_utc"], "evidence": evidence}), evidence)
    return {"outcome": decision["outcome"], "confidence": decision["confidence"], "summary": decision["summary"], "delivery_evidence": delivery_snapshot, "evidence_commitment": commitment, "review_hash": _sha256(_canonical_json({"claim_id": claim["id"], "baseline_hash": claim["baseline_hash"], "evidence_commitment": commitment, "outcome": decision["outcome"]}))}


def _resolution(claim: dict, review: dict, challenge: dict) -> dict:
    evidence = list(claim["baseline_evidence"]) + [review["delivery_evidence"], challenge["counterevidence"]]
    commitment = _evidence_commitment(claim["baseline_hash"], evidence)
    decision = _decision(_judge("delivery_challenge", {"promise": claim["promised_delivery"], "review_outcome": review["outcome"], "evidence": evidence}), evidence)
    return {"outcome": decision["outcome"], "confidence": decision["confidence"], "summary": decision["summary"], "evidence_commitment": commitment, "resolution_hash": _sha256(_canonical_json({"claim_id": claim["id"], "review_hash": review["review_hash"], "challenge_id": challenge["id"], "baseline_hash": claim["baseline_hash"], "evidence_commitment": commitment, "outcome": decision["outcome"]}))}


def _judge(stage: str, context: dict) -> dict:
    prompt = """You are a GenLayer consensus delivery adjudicator. Use only immutable supplied evidence. Decide delivered, not_delivered, or inconclusive. Return JSON with outcome, confidence, summary. Do not introduce outside facts."""
    try:
        return json.loads(gl.nondet.exec_prompt(prompt + "\\nStage: " + stage + "\\nContext: " + _canonical_json(context)))
    except Exception:
        return {"outcome": "inconclusive", "confidence": 0, "summary": "No parseable consensus verdict."}


def _decision(data: dict, snapshots: typing.Sequence[dict]) -> dict:
    outcome = _choice(str(data.get("outcome", "inconclusive")).lower(), ["delivered", "not_delivered", "inconclusive"])
    if sum(1 for item in snapshots if item["snapshot_hash"]) < 2:
        outcome = "inconclusive"
    return {"outcome": outcome, "confidence": _u8(data.get("confidence", 0)), "summary": _clean(str(data.get("summary", "No structured explanation returned.")), 280, "summary_required")}


def _render_all(sources: typing.Sequence[dict]) -> typing.Sequence[dict]:
    return [_render(source) for source in sources]


def _render(source: dict) -> dict:
    try:
        content, error = _bounded(gl.nondet.web.render(source["canonical_url"], mode="text"), SNAPSHOT_LIMIT), ""
    except Exception as exc:
        content, error = "", _bounded(str(exc), 240)
    return {"role": source["role"], "canonical_url": source["canonical_url"], "content": content, "snapshot_hash": _sha256(content) if content else "", "fetch_error_hash": _sha256(error) if error else ""}


def _commitments(snapshots: typing.Sequence[dict]) -> typing.Sequence[dict]:
    return [{"role": item["role"], "canonical_url": item["canonical_url"], "snapshot_hash": item["snapshot_hash"], "fetch_error_hash": item["fetch_error_hash"]} for item in snapshots]


def _evidence_commitment(baseline_hash: str, snapshots: typing.Sequence[dict]) -> str:
    return _sha256(_canonical_json({"baseline_hash": baseline_hash, "snapshot_commitments": _commitments(snapshots)}))


def _same_decision(left: dict, right: dict, stage: str) -> bool:
    keys = ["outcome", "evidence_commitment", "review_hash" if stage == "review" else "resolution_hash"]
    return all(left[key] == right[key] for key in keys)


def _load(records, record_id: str, error: str) -> dict:
    raw = records.get(record_id.strip(), "")
    if not raw:
        raise Exception(error)
    return json.loads(raw)


def _source(role: str, url: str) -> dict:
    clean = str(url).strip()
    if not clean.startswith("https://") or len(clean) > 280:
        raise Exception(role + "_url_required")
    return {"role": role, "canonical_url": clean}


def _clean(value: str, limit: int, error: str) -> str:
    clean = " ".join(str(value).strip().split())
    if not clean or len(clean) > limit:
        raise Exception(error)
    return clean


def _window(value: str) -> int:
    amount = int(str(value).strip())
    if amount < 60 or amount > 604800:
        raise Exception("invalid_challenge_window")
    return amount


def _choice(value: str, choices: typing.Sequence[str]) -> str:
    return value if value in choices else "inconclusive"


def _u8(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except Exception:
        return 0


def _bounded(value: str, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> int:
    try:
        return int(gl.block.timestamp)
    except Exception:
        return 0
