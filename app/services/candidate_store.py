"""Stockage des candidats dans une base SQLite : ils survivent aux redémarrages de l'API.

Sans chemin, la base est en mémoire (tests, scripts) et disparaît avec l'objet.
"""

import sqlite3
import threading
import uuid
from pathlib import Path

from app.models.candidate import Candidate, CandidateStatus
from app.models.cv_analysis import CVAnalysis

IN_MEMORY = ":memory:"

# Parcours d'un candidat : nouveau → analysé → entretien planifié → retenu / refusé.
# Un candidat analysé peut aussi être refusé sans entretien.
ALLOWED_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.NEW: frozenset({CandidateStatus.ANALYZED}),
    CandidateStatus.ANALYZED: frozenset({CandidateStatus.INTERVIEW_SCHEDULED, CandidateStatus.REJECTED}),
    CandidateStatus.INTERVIEW_SCHEDULED: frozenset({CandidateStatus.ACCEPTED, CandidateStatus.REJECTED}),
    CandidateStatus.ACCEPTED: frozenset(),
    CandidateStatus.REJECTED: frozenset(),
}


class CandidateNotFoundError(Exception):
    def __init__(self, candidate_id: str) -> None:
        super().__init__(f"Aucun candidat avec l'identifiant {candidate_id!r}.")
        self.candidate_id = candidate_id


class InvalidStatusTransitionError(Exception):
    def __init__(self, current: CandidateStatus, target: CandidateStatus) -> None:
        super().__init__(f"Passage du statut {current.value!r} à {target.value!r} interdit.")
        self.current = current
        self.target = target


class CandidateStore:
    def __init__(self, path: str = IN_MEMORY) -> None:
        if path != IN_MEMORY:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Partagée entre la boucle asyncio et le pool de threads de FastAPI : accès protégés par un verrou
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        # RGPD : une ligne supprimée est écrasée dans le fichier, pas seulement marquée comme libre
        self._connection.execute("PRAGMA secure_delete = ON")
        with self._lock, self._connection:
            # Le candidat est enregistré en JSON (validé par Pydantic) : le schéma suit le modèle sans migration
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS candidates (id TEXT PRIMARY KEY, data TEXT NOT NULL)"
            )

    def close(self) -> None:
        self._connection.close()

    def add(self, *, name: str, email: str | None) -> Candidate:
        candidate = Candidate(id=uuid.uuid4().hex, name=name, email=email)
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO candidates (id, data) VALUES (?, ?)", (candidate.id, candidate.model_dump_json())
            )
        return candidate

    def get(self, candidate_id: str) -> Candidate:
        with self._lock:
            return self._read(candidate_id)

    def list_all(self) -> list[Candidate]:
        """Renvoie les candidats dans l'ordre où ils ont été ajoutés."""
        with self._lock:
            rows = self._connection.execute("SELECT data FROM candidates ORDER BY rowid").fetchall()
        return [Candidate.model_validate_json(data) for (data,) in rows]

    def delete(self, candidate_id: str) -> None:
        """Supprime définitivement le candidat et son analyse (droit à l'effacement, RGPD)."""
        with self._lock, self._connection:
            deleted = self._connection.execute("DELETE FROM candidates WHERE id = ?", (candidate_id,)).rowcount
        if not deleted:
            raise CandidateNotFoundError(candidate_id)

    def find_all_by_email(self, email: str) -> list[Candidate]:
        """Renvoie les candidats ayant cet email (sans tenir compte de la casse), du plus ancien au plus récent.

        Plusieurs dossiers peuvent partager un email (ex. adresse familiale) : à l'appelant de départager.
        Un email vide ne correspond à aucun dossier.
        """
        wanted = email.strip().casefold()
        if not wanted:
            return []
        return [candidate for candidate in self.list_all() if (candidate.email or "").strip().casefold() == wanted]

    def update_status(self, candidate_id: str, status: CandidateStatus) -> Candidate:
        return self._transition(candidate_id, status)

    def record_analysis(self, candidate_id: str, analysis: CVAnalysis) -> Candidate:
        """Enregistre l'analyse du CV et passe le candidat au statut « analysé »."""
        return self._transition(candidate_id, CandidateStatus.ANALYZED, analysis=analysis)

    def replace_analysis(self, candidate_id: str, *, name: str, analysis: CVAnalysis) -> Candidate:
        """Remplace l'analyse d'un candidat déjà suivi (CV mis à jour), sans changer son statut."""
        with self._lock, self._connection:
            candidate = self._read(candidate_id)
            updated = candidate.model_copy(update={"name": name, "analysis": analysis})
            self._write(updated)
        return updated

    def _transition(self, candidate_id: str, status: CandidateStatus, **changes: object) -> Candidate:
        # Lecture, contrôle et écriture sous le même verrou : deux transitions simultanées
        # ne peuvent pas partir du même statut, ni écrire un candidat supprimé entre-temps
        with self._lock, self._connection:
            candidate = self._read(candidate_id)
            if status not in ALLOWED_TRANSITIONS[candidate.status]:
                raise InvalidStatusTransitionError(candidate.status, status)
            updated = candidate.model_copy(update={"status": status, **changes})
            self._write(updated)
        return updated

    def _read(self, candidate_id: str) -> Candidate:
        """À appeler verrou tenu."""
        row = self._connection.execute("SELECT data FROM candidates WHERE id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise CandidateNotFoundError(candidate_id)
        return Candidate.model_validate_json(row[0])

    def _write(self, candidate: Candidate) -> None:
        """À appeler verrou tenu."""
        self._connection.execute(
            "UPDATE candidates SET data = ? WHERE id = ?", (candidate.model_dump_json(), candidate.id)
        )
