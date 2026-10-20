from evallab.veto import qualifies

SUBJECTS = {"ENG-WKS-0311", "corp\\t.brennan"}
is_subject = SUBJECTS.__contains__


def test_qualifying_technique_on_shared_host():
    assert qualifies({"technique_id": "T1003.001", "shared_entity": "ENG-WKS-0311"}, is_subject)


def test_qualifying_technique_on_shared_user():
    assert qualifies({"technique_id": "T1547.001", "shared_entity": "corp\\t.brennan"}, is_subject)


def test_technique_outside_the_veto_set():
    assert not qualifies({"technique_id": "T1087.002", "shared_entity": "ENG-WKS-0311"}, is_subject)


def test_shared_file_name_does_not_count():
    assert not qualifies({"technique_id": "T1053.005", "shared_entity": "CM_Software_Metering"}, is_subject)
