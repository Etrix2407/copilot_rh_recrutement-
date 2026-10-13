from app.data.hr_policies import HR_POLICIES
from app.services.policy_index import PolicyIndex


def test_reindexing_updates_instead_of_duplicating(policy_index: PolicyIndex) -> None:
    policy_index.index(HR_POLICIES)
    policy_index.index(HR_POLICIES)

    assert policy_index.count() == len(HR_POLICIES)


def test_search_returns_closest_policy_with_its_title(policy_index: PolicyIndex) -> None:
    policy_index.index(HR_POLICIES)

    excerpts = policy_index.search("RTT non pris et Compte Épargne Temps", limit=3)

    assert len(excerpts) == 3
    assert excerpts[0].id == "rh_doc_02"
    assert excerpts[0].title == "Politique de Congés & RTT"
    assert "10 jours de RTT" in excerpts[0].text
