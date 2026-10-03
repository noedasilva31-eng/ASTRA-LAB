# Correction ciblée du bridge

## Preuve reçue

Utilisateur : Windows, 312/312 PASS, PumpSwap Mainnet et WebSocket réels PASS.
Bridge : `evidence_exception_ValueError`, sans traceback ; rapport nommé
`all-validation-tfyzt4x`, non joint et absent du workspace de cette session.
Ces éléments ne permettent pas d'identifier avec certitude l'unique exception
survenue sur le poste Windows. Les PASS Observer ne sont pas remis en cause.

## Défaut logiciel reproduit sur le code livré

`source.stream` conserve sa référence genesis pendant la session. Au premier
événement, `Collector.collect` appelle à son tour `identity()`, qui archive une
nouvelle preuve genesis. À la transaction suivante, le moteur live reçoit encore
la première référence. Le replay Observer sélectionne la dernière preuve genesis
précédant chaque transaction. Les données métier peuvent donc être identiques,
mais leurs provenances diffèrent : `materialization_replay_mismatch`.

Le filtre `reason()` ne connaissait pas ce code issu d'Observer et le remplaçait
par `evidence_exception_ValueError`. Le rapport perdait aussi l'étape, l'emplacement
et les résultats partiels. Ce défaut correspond au symptôme rapporté, sans prouver
que le rapport Windows absent ne contient aucune autre cause.

Reproduction avant correctif : le nouveau test
`test_interleaved_collector_genesis_replay` échoue avec exactement
`ValueError: materialization_replay_mismatch`. Une seconde régression exerce le
vrai `Collector.identity()` avec transport simulé et quotes indisponibles.

## Correction

Le bridge choisit, à l'ingestion, la dernière preuve genesis vérifiée **antérieure
au brut de la transaction**, comme le replay existant. Ni Observer, ni ses critères,
ni le décodeur, ni le ledger paper, ni les TTL/vetos Risk n'ont été modifiés.

Les diagnostics exportent uniquement des codes contrôlés, le type d'exception,
l'étape et un emplacement relatif au code (fichier/fonction/ligne), jamais le texte
arbitraire d'une exception, un endpoint, des variables locales ou une clé.

Catégories : EVIDENCE_REJECT, SOURCE_FAILURE, OPERATIONAL_FAILURE,
INTEGRITY_FAILURE et SOFTWARE_EXCEPTION. Une exception inconnue n'est plus
convertie en rejet marché. Elle remonte en FAIL. L'échec amont produit aussi un
FAIL explicite pour le contrôle round-trip, plutôt qu'un NOT_EXECUTED ambigu.

Si l'acquisition et le replay fonctionnent mais que les preuves marché restent
insuffisantes : décisions REJECT, qualification evidence FAIL avec ses raisons,
round-trip NOT_EXECUTED. Aucun PASS d'evidence n'est déduit du seul décodage d'un
événement ou d'un refus sans preuve. Aucun fill n'est fabriqué.

## Validation et reprise

Les fichiers de `astra_observer` sont inchangés octet pour octet. La gate locale
finale conserve les contrôles réseau absents comme non qualifiés. La nouvelle
version n'est pas annoncée PASS Windows/Mainnet.

Exécuter `validate-all.cmd` dans le nouveau dossier Windows. Les bases de validation
sont nouvelles ; ne pas remplacer les bases d'une session ancienne, dont le code
et la configuration sont volontairement immuables. Les rapports JSON/texte donnent
maintenant directement catégorie, étape et emplacement lorsque disponibles.
