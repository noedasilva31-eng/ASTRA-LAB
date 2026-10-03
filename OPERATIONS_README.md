# ASTRA — preuve SOL bornée et alertes persistantes

Le rapport Windows fourni confirme 189/189 tests PASS et un seul FAIL :
V1d/live_memory, absence d'un transfert SOL compatible dans six slots.
Cela prouve une insuffisance de l'échantillon, pas une erreur du décodeur.

La gate permanente reste :

```bat
validate-all.cmd
```

## Contrôle réel SOL corrigé

Les modules et validateurs V1b/V1c/V1d/V1e restent inchangés. Le lanceur racine
emploie un adaptateur pour V1d : tous les contrôles originaux sont exécutés,
seule la sélection de la preuve `live_memory` est remplacée. Les anciens
lanceurs isolés sont conservés pour historique ; utiliser la gate racine.

1. Vérifier les blocs de la plage initiale et chercher une instruction SOL
   effectivement décodable, sans erreur de décodage dans le bloc témoin.
2. À défaut, rechercher au maximum **64 slots finalisés antérieurs**, dans un
   journal distinct. Chaque réponse brute/erreur est archivée avant traitement.
   Budget persistant : **66 tentatives HTTP**, contexte inclus. Deadline de
   recherche : 100 s, timeout RPC 8 s, arrêt du worker à 120 s au maximum.
3. Sélectionner un bloc réel compatible, conserver sa réponse brute exacte,
   ses paramètres, la finalité, les hashes et les identifiants des événements.
4. Dans un **nouveau processus sans endpoint et réseau interdit**, exécuter les
   vérifications V1d existantes : import, reprise, déduplication, export et
   reconstruction du dataset. Au moins un événement SOL réellement décodé est requis.

La recherche n'est pas une garantie mathématique de trouver un transfert :
si aucun témoin n'est trouvé dans les bornes, `sol_probe_exhausted` reste FAIL.
Aucune transaction n'est créée pour faire passer le test. Aucun transfert n'est
inventé à partir d'une plage vide. Aucune fixture simulée ne vaut preuve réelle.
Les simulations servent exclusivement aux tests de régression locaux.

Les journaux de recherche et de preuve ainsi que `dataset.json` sont conservés
dans `memory_validation/memory-report-*`. Le rapport indique ce chemin.
Les bases sont sauvegardées par l'API SQLite, WAL compris, même après timeout.
Le rapport contient la plage réellement examinée, les erreurs/slots non visités,
le slot sélectionné, les compteurs, le budget et le hash brut. La sélection d'un
bloc témoin ne transforme pas la plage de recherche en couverture complète.
Le replay est déterministe une fois cette capture conservée ; les exécutions
futures continuent de vérifier du réel plutôt que de recycler un PASS ancien.

## Progression V1 : journal d'alertes opérationnelles

`astra_operations/alerts.py` ajoute un journal local SQLite append-only.
Les commandes `run-pipeline.cmd run ...` et `run-pipeline.cmd poll ...` y écrivent
automatiquement dans `<workdir>/alerts.sqlite` ou `<directory>/alerts.sqlite`.
Le rapport expose les alertes actives et les transitions OPEN/RESOLVED.

- Déduplication par source et empreinte du rapport ; aucun double événement à
  la reprise d'un rapport identique.
- Une observation incomplète ne peut pas résoudre une alerte existante.
- Un rapport de succès ne résout pas le quota si le budget reste entièrement consommé.
- Reprise/replay de l'historique et snapshot/reconstruction dans un nouveau fichier.
- Hashes couvrant observations et identité ; corruption bloquante.
- Uniquement des codes prédéfinis : aucun corps d'exception, URL ou secret
  contenu dans un rapport n'est recopié dans le journal.

Le code normalise les rapports du pipeline, conserve une empreinte du rapport
source et dérive les transitions de manière reproductible. Ce journal est un
composant d'observation ; il ne remplace pas les garde-fous des collecteurs.
Il n'effectue **aucun envoi externe**. Notification/escalade, supervision continue
et qualification des politiques d'alerte restent à intégrer.

## État et reprise

Les fichiers de référence restent intacts. Seuls le lanceur racine et la CLI
pipeline sont étendus, dans ce nouveau dossier. Rapports/checklist et point de
reprise courant : `operations_handoff/`. Le contrôle réel de cette correction
n'est pas exécuté ici faute d'endpoint ; le PASS Windows précédent est conservé
comme preuve historique distincte. V1 complète reste non terminée.
