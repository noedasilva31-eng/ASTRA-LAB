# Reprise — pipeline intégré

Réalisé dans une seule version : transport RPC soumis aux quotas persistants,
reprise et retries bornés, décodeur SPL TransferChecked classique, variations
pré/post des soldes token avec inconnus explicites, frais/statuts transactions,
index métier idempotent, exports JSONL, dataset autonome vérifiable, replay hors
réseau, comparaison d'archives sans arbitrage et diagnostics locaux. Ordonnanceur séquentiel de plages, reçus persistants,
attente de finalité et reprise sans avancement prématuré du curseur. La gate
racine inclut désormais ces composants et le scénario réel d'intégration.

Première action d'intégration sur Windows, endpoint déjà configuré :

```bat
validate-all.cmd
```

Il s'agit d'un jalon d'intégration, pas d'une validation manuelle de chaque
modification. Le résumé racine donne tout FAIL avec son contrôle/code/cause.
Aucune nouvelle capacité n'est qualifiée Windows/Devnet avant ce PASS réel.

Pour utiliser le pipeline après ce contrôle :

```bat
run-pipeline.cmd run --workdir work\devnet-session --slots 12 --request-limit 100
```

Relancer la même commande reprend la même plage sans doublon. Consulter les
exports `business/datasets/*.events.jsonl` et `*.transactions.jsonl`, et vérifier
le JSON autonome avec la commande `replay`. Ne pas joindre la valeur de l'endpoint.

Travail suivant selon dépendances, dans le même flux d'intégration :
1. Étendre les décodeurs aux programmes/pools DEX effectivement ciblés par V1,
   avec fixtures réelles versionnées et sémantique vérifiée ; ne pas appeler un
   simple delta « swap » ni additionner instructions et effets nets.
2. Supervision continue du poll borné existant, backpressure à qualifier sous
   charge, politique de quotas fournisseur
   et alertes persistantes/escaladées. Les quotas actuels bornent les tentatives,
   pas le tarif fournisseur ni le débit par seconde.
3. Réconciliation sur deux sources indépendantes réelles : l'outil compare les
   archives mais ne prouve pas l'indépendance des fournisseurs. Dépend de sources
   externes autorisées ; aucun endpoint n'est inventé.
4. Archive distante avec rétention et restauration réellement exercée, horloges
   et reçus d'offsets côté consommateur, disponibilité physique qualifiée.
5. Qualification opératoire/soak 72 h et seuils de lag/couverture fixés avant mesure.

Ne pas restaurer un ancien budget pour effacer une consommation active. Ne pas
fusionner une source conflictuelle à une autre. Le dataset conserve la couverture
incomplète et les erreurs. Les codes et formats des baselines V1b–V1f restent
conservés, hormis l'extension du lanceur racine et ses rapports générés.
V1 entière reste NON VALIDÉE : tests PASS ne remplacent pas ces objectifs.
