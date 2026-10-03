# ASTRA — runner V1b automatisé

Version corrigée de **ASTRA-V1b-rpc-conflict(1).zip** : voir `../CORRECTION_WINDOWS.md`.
Le runner ne modifie ni le code ASTRA ni ses bases de référence. L’adaptateur appelle
les vraies API `rpc_capture`, `capture_rpc`, `replay_rpc`, `redeliver_rpc`,
`conflict_rpc`, `recover` et `backup` de cette version.

## Lancer toute la validation sous Windows

Python 3.12+ avec lanceur `py`, aucune dépendance pip. Décompresser ce package
et le projet ASTRA. La variable **SOLANA_RPC_URL** doit déjà être définie dans
le terminal par votre mécanisme de configuration habituel. Ne pas inscrire sa
valeur dans les scripts, rapports ou messages.

Depuis le dossier du runner, dans PowerShell :

```powershell
.\run-v1b.cmd "C:\chemin\ASTRA-V1b-rpc-conflict"
```

Le chemin désigne le dossier contenant `astra\store.py` et `tests\`.
Le runner n’utilise aucun endpoint par défaut ; HTTPS est exigé. Le produit
étiquette actuellement sa provenance réseau `solana-devnet` : utiliser un
endpoint **Devnet** pour que cette provenance soit correcte.

Rapports : un nouveau dossier `v1b-report-*` à côté du runner, avec
**report.json** et **report.txt**. Tous les compteurs, publications et hashes
sont vérifiés automatiquement. Le rapport contient le hash des sources et de
l’adaptateur réellement utilisés, les preuves numériques et les échecs par critère.

Codes de sortie : **0 = tous PASS**, **1 = au moins un FAIL**, **2 = configuration
invalide**. Un FAIL peut indiquer un prérequis réseau absent, pas seulement un
défaut du produit. Chaque worker est borné ; un processus tué pour dépassement
de délai reste FAIL et n’est jamais compté comme un timeout réussi du produit.

Mode sans fournisseur :

```powershell
.\run-v1b.cmd "C:\chemin\ASTRA-V1b-rpc-conflict" --self-test
```

Ce mode valide les scénarios locaux avec une fixture explicitement synthétique.
Les deux critères live restent FAIL (`live_capture_unavailable`) et la sortie
vaut 1. Sans variable d’environnement ou si la capture échoue, le runner poursuit
également les tests locaux avec cette fixture, sans présenter ces tests comme live.

Autres systèmes : `python3 validate_v1b.py --project /chemin/ASTRA-V1b-rpc-conflict`.

## Couverture et assertions

| Critère | Vérification automatisée |
|---|---|
| Tests du dépôt | Suite unittest existante ; résultats individuels, réseau bloqué |
| Capture réelle | Appel RPC via l’environnement, réponse JSON-RPC valide, accepted=1 et une publication |
| Brut et provenance | Octets inchangés, SHA-256, heure de réception, provenance exacte ; pending=1 avant normalisation |
| Replay | Vrai `replay_rpc`, comparaison indépendante du document et du hash, aucune mutation |
| Reprise avant normalisation | Arrêt brutal d’un sous-processus après capture durable ; pending=1 puis recover, une publication et replay identique |
| Reprise avant publication | Arrêt après normalisation durable ; unpublished=1 puis recover et replay identique |
| Recover idempotent | Deux recover, toutes les lignes des quatre tables strictement identiques, dates incluses |
| Redelivery | Vrai `redeliver_rpc` ; accepted=1, duplicate=1, une publication, brut redélivré et original inchangés |
| Conflit | Vrai `conflict_rpc` ; raison exacte `source ID conflict`, original intact, replay original identique |
| Ingestion après quarantaine | Nouvelle identité synthétique distincte ; accepted=2, quarantined=1, deux publications |
| Backup/restauration | Deux fichiers distincts, toutes les lignes et snapshot identiques, deux recover sans mutation, deux replays identiques |
| Intégrité | SHA-256 recalculés indépendamment ; corruptions brute/document injectées uniquement dans une base jetable et détectées |
| RPC indisponible | Vrai serveur TCP local muet, timeout produit <=20 s, aucune écriture ; limite worker 25 s |
| Retour du RPC | Après succès du test de panne, seconde collecte réelle, identité distincte, accepted=2 et replay vérifié |

Les invariants communs vérifient `pending=0`, `unpublished=0`, `integrity=ok`,
aucune erreur de hash, et le nombre exact de publications. **healthy=false est
exigé en présence d’une quarantaine**. Les états transitoires avec pending ou
unpublished sont également attendus dégradés.

Les scénarios de conflit et d’identité distincte emploient des variantes
synthétiques clairement identifiées, même lorsque la capture de base est réelle.
Le retour à une nouvelle observation réelle est testé séparément. Les tests
hors réseau bloquent les connexions socket ; aucune manipulation d’Internet
n’est nécessaire. La panne est locale, contrôlée, et ne sollicite pas le fournisseur.

## Isolation et confidentialité

- Copie temporaire des seuls fichiers Python de `astra/` et `tests/`, plus
  l’adaptateur. Les fichiers de `var/` ne sont jamais lus ni copiés.
- Une base neuve par critère. Aucune option ne permet de désigner une base cible.
- Le code testé s’exécute depuis la copie temporaire. Ce mécanisme isole ce
  projet connu ; ce n’est pas une sandbox pour du code hostile.
- Captures, sauvegardes et restaurations sont supprimées à la sortie normale.
  Un arrêt forcé du PC peut laisser un répertoire `astra-v1b-isolated-*` dans le
  dossier temporaire système. Aucun effacement sécurisé du disque n’est revendiqué.
- L’endpoint complet passe seulement par l’environnement des workers live,
  jamais par leurs arguments. La provenance archivée utilise l’origine expurgée
  renvoyée par le produit ; aucun token de chemin/query ni mot de passe n’y figure.
- Pas de payload, URL, traceback ou message brut du fournisseur dans les rapports.
  Les sorties du produit sont supprimées ; seules des preuves contrôlées sont
  rapportées. Les réponses reflétant les identifiants détectables de l’endpoint
  sont refusées avant leur enregistrement temporaire.
- Les proxies d’environnement ne sont pas hérités. Un réseau imposant un proxy
  peut faire échouer la collecte. Les variables de certificats SSL sont conservées.

## Ce qui nécessite réellement une action humaine

**Définir SOLANA_RPC_URL et lancer la commande** sur un poste autorisé à accéder
au fournisseur. Aucun examen manuel des compteurs, changement de base ou coupure
réseau n’est demandé. Il n’est plus nécessaire de fournir d’autres sources pour
cette version.

Une coupure électrique physique n’est pas simulée : les tests interrompent des
processus avec `os._exit`, après les frontières durables prévues. Restauration
distante, couverture/forks/décodeurs, multi-provider et soak 72 h restent hors
périmètre des primitives disponibles. Ils peuvent être automatisés avec leurs
implémentations et environnements dédiés ; un PASS ici ne qualifie pas V1 complet.

## Vérifier le runner lui-même

```powershell
py -3 check_runner.py --project "C:\chemin\ASTRA-V1b-rpc-conflict"
```

Cette suite teste notamment qu’un recover cassé, un replay cassé, une provenance
absente et un worker bloqué sont effectivement détectés. `VALIDATION.md` décrit
les vérifications réellement exécutées pour cette livraison. `example-report/`
contient le rapport synthétique, clairement distinct d’une exécution live.
