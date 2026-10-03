# ASTRA — premier pipeline intégré de données Devnet

Cette livraison prolonge la baseline Windows/Devnet V1f (159 tests PASS), sans
la modifier. La preuve reçue est dans `integration_handoff/baseline-windows-summary.json`.
Le développement a continué dans un seul dossier d'intégration ; pas de nouvelle
validation manuelle par micro-brique. `validate-all.cmd` reste la gate permanente.

## Usage réel

Avec Python 3.12+ et `SOLANA_RPC_URL` déjà défini, depuis ce dossier :

```bat
run-pipeline.cmd run --workdir work\devnet-session --slots 12 --request-limit 100
```

Cette commande collecte douze slots finalisés récents, archive les réponses,
reprend les captures pendantes, effectue jusqu'à trois passes de retry si
nécessaire, reconstruit la provenance et publie un dataset métier avec exports
JSONL. Elle ne crée ni portefeuille, ni transaction financière.

Relancer exactement la même commande reprend la plage existante. Une plage
complète ne déclenche pas de nouvel appel RPC ni de republication. Pour une
nouvelle plage, choisir un nouveau workdir. `--start` et `--end` permettent de
fixer une plage de 1 à 1000 slots. `--max-slots 3` permet une interruption
volontaire : le rapport reste FAIL/incomplet jusqu'à la reprise normale.
Aucune base de référence n'est utilisée par défaut.

Les fichiers utiles sont dans le workdir :

- `blocks.sqlite` : brut, tentatives, erreurs historiques, checkpoint et publications.
- `quota.sqlite` : réservations de chaque tentative HTTP, y compris genesis/tip.
- `business/provenance.sqlite` : captures et versions de provenance.
- `business/business.sqlite` : versions de datasets et événements métier uniques.
- `business/datasets/<hash>.json` : dataset autonome, brut et preuves inclus.
- `business/datasets/<hash>.events.jsonl` : événements métier et provenance.
- `business/datasets/<hash>.transactions.jsonl` : statuts, frais et couverture.
- `pipeline-report.json` : compteurs, état de complétude et alertes locales.

Les exports JSONL se lisent avec les outils habituels de traitement JSON et
conservent les montants en chaînes d'entiers. Le fichier JSON autonome est la
source de vérification ; les JSONL sont des vues reconstruisibles.

## Enchaîner des plages sans trous

```bat
run-pipeline.cmd poll --directory work\feed --range-size 12 --max-batches 2 --request-limit 300
```

L'ordonnanceur traite les plages successivement, avec un budget partagé et des
reçus de publication persistants. Son prochain slot est reconstruit depuis les
reçus vérifiés ; il n'avance qu'après réussite complète de la plage. Réexécuter
la même commande continue au bon endroit. `WAIT / waiting_for_finality` conserve
le curseur si la plage suivante n'est pas encore finalisée. Une erreur ou un
quota épuisé conserve également le travail à reprendre. Les effets d'un crash
entre export et reçu sont récupérés sans renvoyer les blocs déjà terminés.

`poll` est borné (1 à 100 plages par invocation), séquentiel et destiné à un seul
ordonnanceur par répertoire. Il n'est pas encore un daemon supervisé avec
politique de relance. La sélection initiale récente est explicite dans le
premier reçu ; elle ne prétend pas couvrir l'historique antérieur. Pour une
origine précise, fournir `--start`. Conserver la même taille de plage à la reprise.

## Quotas réellement branchés au RPC

Chaque tentative HTTP réserve durablement une demande et une unité **avant**
le transport, y compris les requêtes de contexte et les retries. Une interruption
ou un timeout ne rembourse pas une tentative incertaine. Le plafond empêche
l'appel suivant ; les slots non visités restent explicitement non résolus.
La politique du fichier de budget est immuable. Réutiliser les mêmes paramètres
à la reprise ; pas de remise à zéro implicite.

Pour partager un plafond entre plusieurs workdirs, ajouter le même chemin :

```bat
run-pipeline.cmd run --workdir work\plage2 --slots 12 --request-limit 100 --budget-db work\shared-quota.sqlite
```

Sans `--budget-db`, le plafond est propre au workdir. Les unités comptent les
tentatives HTTP, **pas les crédits facturés par Helius**. Il reste à intégrer une
politique fournisseur pour prétendre maîtriser les coûts monétaires. Le quota
n'est pas un limiteur de débit par seconde. Une nouvelle tentative après une
réponse perdue consomme une nouvelle réservation ; elle n'est pas présentée
comme un envoi réseau exactement une fois.

## Données métier disponibles

| Type | Interprétation |
|---|---|
| `sol_transfer` | Transfert SOL natif de premier niveau déjà décodé par V1d |
| `spl_transfer_checked` | Instruction TransferChecked réussie du Token Program classique, montant brut, mint, décimales et comptes |
| `token_balance_change` | Observation des soldes token pré/post d'une transaction réussie ; delta net exact seulement si les deux côtés sont compatibles |

Les variations de soldes permettent d'observer aussi des effets nets de CPI et
les soldes exposés pour Token-2022, sans supposer le succès individuel d'un CPI
ni inventer la sémantique de ses extensions. Une apparition/disparition de solde
n'est pas remplacée par zéro : `delta_known=false`, `delta_raw=null`, côtés
présents conservés. Un changement de mint/décimales/programme n'est pas additionné.
Les transactions échouées n'émettent aucun transfert métier. Leurs statuts et
frais restent comptabilisés dans la vue transactions.

Un TransferChecked décrit une instruction ; un delta décrit un effet net. Ne
pas les additionner comme des flux distincts. Les transferts SOL, frais, swaps,
créations de compte et mouvements de liquidité ne sont pas inférés à partir
d'un seul delta. Les autres instructions restent unsupported et les métadonnées
absentes restent explicites. Les montants sont entiers, jamais calculés avec
`uiAmount` flottant.

Les définitions de format suivent les sources primaires :
https://solana.com/docs/rpc/json-structures et
https://github.com/solana-program/token/blob/main/interface/src/instruction.rs.

## Hors réseau, reprise et comparaison

```bat
run-pipeline.cmd offline --source work\devnet-session\blocks.sqlite --output work\offline-derived
run-pipeline.cmd replay --dataset CHEMIN_DU_DATASET.json --output work\reconstructed
run-pipeline.cmd compare --left DATASET_A.json --right DATASET_B.json
```

`offline` lit la base source via snapshot en lecture seule. `replay` revérifie
le brut, les preuves de slots et le décodeur puis reproduit les exports.
Les empreintes de code refusent une reconstruction silencieuse avec un autre
décodeur. Les étapes source → provenance → index métier se reprennent après
interruption ; les publications de l'index sont atomiques et idempotentes.
Une corruption d'un export existant est signalée, jamais écrasée silencieusement.

`compare` distingue bloc en conflit, contenu divergent pour un même blockhash,
accord des observations et preuve insuffisante. Les sources restent séparées.
Ce contrôle ne prouve pas que deux endpoints sont indépendants ; aucun arbitrage
vers une prétendue vérité ni enrichissement silencieux d'une source par l'autre.

## Validation permanente

```bat
validate-all.cmd
```

Exécute toutes les non-régressions précédentes, les tests du pipeline, puis un
contrôle d'intégration Devnet sur douze slots : interruption après trois slots,
reprise dans un nouveau processus, quota réellement consommé, données token et
reconstruction hors réseau. Une plage sans événement token observable n'est
pas un faux PASS du nouveau décodeur réel. Les bases de validation sont jetables.
`validation-summary.json`/`.txt` donnent les contrôles, codes et causes.
Sans endpoint, les tests locaux passent séparément mais le verdict global reste
FAIL pour les contrôles réels non exécutés. Ne pas confondre avec le PASS Windows
historique de la baseline.

## Limites opérationnelles

Il s'agit d'un pipeline borné avec ordonnanceur reprenable pour collecte/analyse
reproductible, pas encore d'un service supervisé continu ou d'un Engine. Les alertes sont locales dans les rapports :
slots non résolus, erreurs de décodage, soldes non enregistrés/inconnus et
instructions unsupported. Pas encore de livraison externe ni d'escalade.
`ready_for_complete_range_analysis` décrit la couverture de la plage et
l'absence d'erreur, pas une compréhension exhaustive des programmes.
`business_coverage_complete` reste explicitement false.

V1 n'est pas terminée : voir `integration_handoff/NEXT_SESSION.md` et la checklist
fonctionnelle. L'exemple livré est entièrement SYNTHÉTIQUE ; il sert uniquement
à essayer le replay et les vues métier sans endpoint.
