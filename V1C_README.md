> Correctif courant : lire `DIAGNOSTIC_CORRECTION.md` (transactions v1, retries et preuve Windows reçue).

# ASTRA V1c — chronologie incrémentale de blocs finalisés

Nouvelle version distincte, dérivée exclusivement de `ASTRA-V1b-windows-fix`.
**Tous les fichiers du socle V1b sont conservés octet pour octet**, y compris
`validate-windows.cmd`, son correctif SQLite, ses tests et son validator.
`V1B_REFERENCE.json` contient leurs empreintes ; la validation vérifie cette identité.
Aucune base de référence n’est incluse ni ouverte par les validations.

## Une commande Windows

Extraire dans un nouveau dossier. Python 3.12+ et `SOLANA_RPC_URL` déjà définie
vers un endpoint Devnet accessible sont les seuls prérequis.

```powershell
.\validate-blocks-windows.cmd
```

Le lanceur exécute les tests blocs et le scénario RPC réel, puis **appelle
`validate-windows.cmd` inchangé**. Les deux suites sont exécutées même si l’une
échoue. Code de sortie 0 uniquement lorsque tout est PASS.
Rapport consolidé JSON + texte dans un nouveau dossier `validation-*` ; rapports
détaillés blocs dans `block_validation/blocks-report-*` et V1b dans
`validator/v1b-report-*`. Aucune lecture manuelle des compteurs n’est nécessaire.

`--self-test` désactive volontairement les contrôles réels ; ils restent FAIL
avec un code explicite, jamais PASS simulé. Sans endpoint dans l’environnement,
les tests locaux s’exécutent également et les prérequis live restent FAIL.
Sur Linux : `python3 validate_all.py` (exécute les équivalents Python du lanceur
V1b ; ne constitue pas une certification Windows).

## Nouveau module séparé

`astra_blocks/` utilise son propre SQLite ; aucune migration ni écriture dans
les tables V1b. Une base V1b fournie par erreur est refusée avant tout changement.
Un fichier de collecte correspond à une plage fixe de 1 à 1 000 slots.

La plage est enregistrée intégralement dès l’initialisation : même avant la
première requête, chaque slot existe avec un état `unavailable/not_attempted`.
Les objets bruts JSON-RPC sont archivés et commités **avant** transformation.
Une seconde transaction lie résultat normalisé, publication unique par slot,
preuve de saut et progression du checkpoint. Une capture encore sans résultat
est rejouée hors réseau à la reprise. Les tentatives, résultats et publications
sont append-only ; seuls l’état courant et le checkpoint sont des projections.

Les réponses transport impossibles à obtenir sont représentées explicitement
par un code sans corps brut. Les erreurs JSON-RPC reçues conservent leur corps
exact. Aucun message RPC arbitraire n’est exposé dans les rapports.

### États et sémantique

| État interne | État de couverture | Sens |
|---|---|---|
| `archived` | `available` | Corps getBlock complet archivé, normalisé et publié une fois |
| `skipped` | `skipped` | Saut étayé par une preuve de parenté vérifiée |
| `unavailable` | `unresolved` | Null, absence de réponse, timeout, rétention ambiguë, ou pas encore tenté |
| `error` | `error` | Erreur RPC/protocole explicite ; non résolue et éligible au retry |

Une absence de résultat, une erreur `-32007`/`-32009`, l’absence d’une liste de
blocs ou un timeout **ne suffisent jamais** pour déclarer un saut.

La preuve retenue est prudente : pour deux blocs archivés A et B, collectés avec
`commitment=finalized`, B doit avoir `parentSlot=A.slot` et
`previousBlockhash=A.blockhash`. Alors seuls les slots strictement entre A et B
peuvent être classés skipped. Aucun bloc déjà publié ne peut occuper cet intervalle.
La preuve est conservée comme référence au bloc enfant ; les deux corps bruts
permettent de la revalider hors réseau. Sans parent archivé, ou au bord de la
plage sans bloc encadrant, le slot reste non résolu. Une contradiction provoque
un arrêt explicite avec la capture conservée, pas une réécriture du passé.

Cette preuve dépend de la vérité des réponses finalisées du fournisseur ; ce
n’est pas une vérification cryptographique indépendante du consensus ni une
réconciliation multi-provider. Les réponses `getGenesisHash` (Devnet attendu)
et `getSlot(finalized)` sont également archivées et hashées. Toute plage au-delà
du tip finalisé vérifié est refusée.

### Checkpoint et retry

`next_slot` est le premier slot sans tentative terminée durablement. Il mesure
l’avancement du parcours initial, **pas la résolution complète**. Les erreurs
rencontrées ne bloquent pas l’enregistrement des slots suivants. Après le
parcours, `--retry-unresolved` retente les états unavailable/error ; les anciennes
tentatives et leurs erreurs restent présentes. Les publications déjà acceptées
ne sont ni réémises ni horodatées à nouveau.

```powershell
py -3 -m astra_blocks --db block-data\devnet.sqlite collect --start 100 --end 105 --max-slots 3
py -3 -m astra_blocks --db block-data\devnet.sqlite collect
py -3 -m astra_blocks --db block-data\devnet.sqlite collect --retry-unresolved
py -3 -m astra_blocks --db block-data\devnet.sqlite audit
```

Les slots 100–105 ci-dessus illustrent la syntaxe seulement ; des données aussi
anciennes peuvent être indisponibles. Le validator choisit **automatiquement
six slots récents**, huit slots derrière le tip finalisé, sans action manuelle.

### Audit, replay et métriques

L’audit vérifie :

`expected_slots = available + skipped + unresolved + error`

Il exige aussi la présence exacte de chaque numéro de slot, les relations
SQLite, le checkpoint dérivé des résultats durables, les SHA-256 des bruts,
la provenance, les documents et les preuves de saut. Les replays reconstruisent
les résultats de toutes les tentatives, erreurs comprises. Les connexions
SQLite se ferment explicitement, y compris dans les tests et les sous-processus.

Métriques : fraction des slots comptabilisés, fraction résolue, slots réellement
tentés, nombre de tentatives, octets bruts, publications et non-résolus.
`healthy=true` signifie journal cohérent, **pas couverture résolue à 100 %** ;
`unresolved` et `resolved_fraction` restent visibles. Ce nouveau champ est propre
au collecteur et ne change jamais la sémantique `health()` de V1b.

## Validation automatique

- 35 tests locaux : quatre états, preuve parentale, erreurs ambiguës, bytes/hashes,
  retry avec historique, corruption, checkpoint, rejeu, doublons, conflits,
  refus de base étrangère et crash réel de sous-processus (`os._exit`).
- Scénario déterministe à six slots, interruption après trois puis reprise.
- Contrôle live : nouvelle base temporaire, collecte de trois slots, sortie du
  processus, nouveau processus pour les trois suivants, retry des non-résolus,
  puis deux recover et tous les replays dans un processus aux sockets bloquées.
- Au moins un bloc réel doit être archivé pour que le contrôle live passe.
  Les réponses temporairement indisponibles restent explicitement comptabilisées.
  Une erreur RPC non résolue après retry empêche le PASS final ; un journal
  cohérent avec zéro bloc publié ne produit plus de PASS de phase.
- Chaque phase est bornée à 90 secondes. Timeout de socket RPC : 8 secondes.
  Un dépassement de la limite globale est FAIL, jamais PASS.
- Puis non-régression V1b complète : 38 tests dépôt, 8 tests runner, 14 critères.

Seule l’origine expurgée de l’endpoint peut être conservée dans la provenance.
Jamais de clé, URL complète, query ou chemin secret dans les arguments ou logs.
L’endpoint n’est pas demandé dans le chat. Les redirects et proxies implicites
sont désactivés ; HTTPS est obligatoire. Les bases du validator sont temporaires.

## Références de conception

- https://solana.com/docs/rpc/http/getblock — paramètres, finalité et structure parentale.
- https://solana.com/docs/rpc/http/getgenesishash — identité du cluster.
- https://github.com/solana-labs/cluster/blob/master/service-env-devnet.sh — genesis Devnet attendu.

Voir `SESSION_REPORT.md` et `NEXT_SESSION.md` pour les preuves de cette livraison
et le point de reprise exact. Le gate V1 complet n’est pas encore satisfait.
