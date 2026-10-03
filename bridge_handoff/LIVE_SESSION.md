# Session paper live bornée — suivi ciblé

## Diagnostic du résultat Windows 74buueu_

L'utilisateur confirme Observer HTTP/WebSocket PASS et Evidence Bridge PASS.
Le rapport et ses captures ne sont pas joints à cette session : le mint concerné,
la phase exacte BUY/SELL et les timings de cette exécution ne sont pas supposés.

Dans le code, `pending_other_token` signifie exactement : une intention existe
et l'événement courant concerne un autre mint. Le ledger refuse d'ouvrir une
nouvelle intention concurrente. Ce code ne désigne pas un défaut de quote ou
un programme token inconnu. La version qualifiée attendait passivement qu'un
nouvel événement compatible arrive dans le flux global pour avancer.

Un round-trip exige successivement intention BUY, preuve ultérieure de règlement,
intention SELL puis nouvelle preuve ultérieure. Sans ces transitions, le contrôle
reste non qualifié. Aucun diagnostic plus spécifique à la capture Windows n'est
inventé à partir de la seule ligne de résumé.

## Changement isolé

`astra_bridge/session.py` orchestre les composants existants, sans modifier
Observer, Evidence, Risk, le décodeur ou le ledger.

1. Découverte par le WebSocket existant. Census/features et Evidence fonctionnent
   comme auparavant. Les rejets restent enregistrés.
2. Dès qu'une intention est entièrement commise, fermer proprement cette phase
   de découverte et passer au suivi ciblé du pool de l'intention.
3. Lire `getSignaturesForAddress(pool)` en confirmé, hydrater les transactions
   réussies dont le slot dépasse le slot de décision/règlement précédent.
4. Réinjecter les vrais bruts obtenus dans le bridge existant. Ne pas produire
   d'événement artificiel ni mettre à jour sa date d'observation pour une quote.
5. Recalculer le pool/phase/taille à suivre après chaque transition. En position,
   attendre un événement plus récent pour proposer SELL. En intention SELL,
   attendre les preuves de règlement postérieures exigées par le ledger.
6. S'arrêter au round-trip complet ou à la limite. Ne pas forcer la fermeture.

Une transaction déjà traitée n'est pas réutilisée pour forcer la prochaine étape.
Une hydratation nulle peut être retentée ; plafond persistant de deux tentatives
par signature, visible dans les statistiques. Les nouvelles signatures peuvent
continuer d'être observées. Les anciennes réponses et erreurs restent archivées.

La découverte et le suivi sont séquentiels : pendant le suivi ciblé, le flux global
n'est pas consommé. Couverture toujours OBSERVED_SUBSET/PARTIAL, jamais exhaustive.
Une liste de huit signatures récentes n'est pas un backfill complet de slots.

## Bornes et état observable

Gate Windows : fenêtre 120 s ; découverte au plus 64 notifications ; 8 signatures
par recherche ciblée ; pause de 1 s entre recherches ; budget persistant partagé
200 tentatives. Transport limité à 5 s par appel. Une opération déjà engagée peut
se terminer après la fenêtre ; le worker global impose son plafond de 180 s.
Le temps passé à acquérir les preuves ne prolonge aucun TTL Risk.

Les frames `paper_session_start`, `paper_session_transition`, `paper_session_tick`
et `paper_session_end` conservent configuration, empreinte du scheduler et métriques.
Le rapport expose directement : phase, cible, intentions, règlements BUY/SELL,
positions, PnL réalisé conditionnel, histogramme de refus, recherches, hydratations,
événements obtenus et motif d'arrêt. Les ticks distinguent signatures anciennes,
failed, déjà traitées, limite de retry et événements correspondant au pool.

États : NO_TRADE, PENDING_BUY, OPEN_POSITION, PENDING_SELL, ROUNDTRIP_OBSERVED.
Les compteurs sont cumulatifs pour le dossier persistant ; les compteurs de polls
concernent l'invocation courante. Le début et la fin sont datés. Les positions restent
ouvertes si la preuve de sortie manque, et le PnL non réalisé n'est pas inventé.

Une panne reste FAIL avec état partiel exportable. Une fin de fenêtre sans cycle
complet reste NOT_EXECUTED pour le contrôle round-trip, même si Evidence est PASS.

## Commandes

Qualification complète, nouveau dossier extrait :

```
validate-all.cmd
```

Le contrôle Bridge utilise automatiquement la session bornée ; les références
qualifiées restent les contrôles obligatoires existants.

Utilisation facultative hors gate, dossier dédié :

```
py -3 -B -m astra_bridge session --directory sessions\mainnet-001 --seconds 120
```

Relancer dans le même dossier reprend intentions/positions depuis le ledger, sans
remettre le budget à zéro. `audit` reconstruit hors réseau. Le kill switch existant
reste applicable entre les exécutions. Aucun ordre réel, wallet ou signature.

Les frais, slippage et résultats restent ceux du modèle conditionnel explicite,
pas des coûts mesurés de transactions exécutées. Le nouveau scheduler n'est pas
annoncé qualifié Windows/Mainnet tant qu'il n'a pas été réellement exécuté.
