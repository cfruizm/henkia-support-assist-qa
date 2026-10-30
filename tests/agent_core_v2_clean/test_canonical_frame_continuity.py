"""Deterministic canonical-frame continuity checks retained by 4C.3.1."""

from app.agent_core_v2_clean.canonical_frame import build_frame,enrich_frame

def memory():return {"pending_goal":{"known_details":{},"intent":"conceptual"},"support_case":{}}
def test_authorized_evidence_enriches_subject():
 f=build_frame("Define it",{"user_act":"new_request","intent":"conceptual","topic_relation":"new_topic","current_goal":"Define it","should_retrieve":True},memory()).to_dict()
 r={"evidence_verdict":{"accepted":True,"selected_evidence":[{"metadata":{"product":"platform_alpha"}}]}}
 e=enrich_frame(f,r,{"mode":"documented_answer"});assert e["subject"]["value"]=="platform_alpha" and e["topic"]["topic_id"]
def test_previous_subject_survives_runtime_new_topic_without_explicit_subject():
 p={"subject":{"type":"product","value":"platform_alpha","canonical_id":"platform_alpha","confidence":.95},"topic":{"topic_id":"topic-a"}}
 f=build_frame("And environments?",{"user_act":"new_request","intent":"unknown","topic_relation":"new_topic","current_goal":"And environments?","should_retrieve":True},memory(),{},p,{})
 assert f.subject.value=="platform_alpha" and f.topic.relation=="same_topic_candidate" and f.topic.topic_id=="topic-a"
def test_ambiguous_evidence_does_not_guess_subject():
 f=build_frame("Question",{"intent":"conceptual","topic_relation":"new_topic","current_goal":"Question","should_retrieve":True},memory()).to_dict()
 r={"evidence_verdict":{"accepted":True,"selected_evidence":[{"metadata":{"product":"a"}},{"metadata":{"product":"b"}}]}}
 e=enrich_frame(f,r,{});assert not e["subject"]["value"] and "accepted_evidence_without_unambiguous_subject" in e["warnings"]
def test_troubleshooting_missing_case_is_visible():
 f=build_frame("Issue",{"intent":"troubleshooting","topic_relation":"new_topic","current_goal":"Issue","should_retrieve":True},memory())
 assert "troubleshooting_without_case_context" in f.warnings
