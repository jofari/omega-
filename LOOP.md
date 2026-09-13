# OMEGA — journal de boucle génération→critique→amélioration

Plafond : 3 tours de critique→amélioration. Stop si une critique ne trouve aucun défaut bloquant.
Chaque critique est jugée contre BRIEF.md (source de vérité), pas contre l'opinion du code.

## Tour 0 — build initial
- statut : TERMINÉ (exit 0) — 14 fichiers livrés (backend + frontend + config + README)

## Tour 1 — critique + amélioration
- critique : FAIT — 14 défauts — fusionnés dans CRITIQUE.md
- amélioration : FAIT — production-grade (to_thread, TTS streamé, sécurité, événementiel)

## Tour 2 — critique + amélioration
- critique : FAIT — 5 défauts restants (uvloop/Win, int_or_none, blur, poll UI, token escape)
- amélioration : EN COURS (proc_e891762b0ffd)

## Tour 3 — critique finale
- DONE : aucun défaut bloquant. Restent uniquement des caveats runtime à vérifier sur le PC
  Windows (micro/navigateur, round-trip Telegram réel, wheels Windows, edge-tts réseau).

**Convergence : 3 tours.** Build → 14 défauts → fix → 5 défauts → fix → clean.