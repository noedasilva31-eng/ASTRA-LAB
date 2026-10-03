# ASTRA — diagnostic et surveillance ciblée de position

Le correctif est dans `astra_watch/`. Observer, Evidence, Risk, Bridge, ledger,
Brain, Context **et astra_position V0.2** restent inchangés (51 fichiers protégés).
La version précédente n'est pas écrasée. Aucun ordre réel, seuil modifié, BUY
supplémentaire ou fermeture imposée.

## Cause du comportement précédent

`astra_position.session.run` reprend toujours `starts[0]`, la première fenêtre
persistée, et compte tous les anciens `position_poll_reserved`. Après 120 s ou
16 polls, la boucle ne passe plus dans les appels RPC. Relancer la même commande
ne réarme ni la fenêtre ni les compteurs. `qualification(0, ...)` convertit ensuite
ce cas en `NOT_EXECUTED | no_new_position_observation`, comme les cas d'absence de
signature ou de décodage. Ce défaut de diagnostic et de renouvellement explicite
est reproduit par les tests, sans supposer une inactivité du pool.

Le code seul ne prouve pas pourquoi la **première** tentative Windows n'a rien
produit. Son dossier `position-continuation` n'a pas été joint à cette demande.
Le run `all-validation-jyqge_an` est la référence d'entrée, pas une trace de cette
nouvelle recherche live. Pour analyser cette première tentative, conserver
`position-report.json`, `position-review.json`, `position-parent.json`, `raw.sqlite`,
`state/engine.sqlite`, `state/paper.sqlite` et les éventuels WAL. Aucune URL/API key.
Aucune relance réseau n'a été effectuée dans Work pour deviner la cause.

## Commande exacte : nouvelle fenêtre

Depuis le dossier extrait contenant ce fichier :

```cmd
resume-position-windows.cmd --seconds 120 --budget 80 --max-polls 60 --poll-seconds 2
```

Chaque invocation **sans --window-id** alloue explicitement une nouvelle fenêtre
identifiée et un budget borné. Son identifiant est affiché et archivé. Les anciens
budgets, fenêtres et raisons d'arrêt restent conservés, sans remise à zéro du
ledger, capital, pertes, quantité, thèse ou observations.

Par défaut, le dossier actif est `position-continuation` à côté de la commande.
S'il existe, son état actuel est chargé et vérifié. S'il n'existe pas, une copie
isolée de la position de référence est créée : ce n'est pas la récupération d'un
autre dossier actif se trouvant ailleurs. **Pour conserver votre continuation
Windows actuelle, placez sa copie dans ce dossier ou indiquez son chemin avec
`--directory`.** Le chemin existant fourni avec --directory devient le dossier
actif, et reçoit les nouvelles archives; ne pointer jamais la référence immuable.

Exemple si les deux dossiers de version sont côte à côte :

```cmd
resume-position-windows.cmd --directory "..\ASTRA-V1-position\position-continuation" --seconds 120 --budget 80 --max-polls 60 --poll-seconds 2
```

Aucune découverte de 50 opportunités. Le watcher ne recherche que le pool de
la position et refuse toute nouvelle entrée BUY. Un HOLD poursuit les polls.
Ctrl+C arrête proprement la surveillance et conserve les données/résultats acquis.
Aucune liquidation à l'échéance.

## Reprise idempotente de la même fenêtre

Pour reprendre après interruption avec les **mêmes** bornes, ajouter
`--window-id IDENTIFIANT_AFFICHE`. Même ID = même échéance et même budget restant,
pas de crédit supplémentaire. Une fenêtre expirée donne `NO_NETWORK_CALL` avec
`stop_reason=window_expired`; une fenêtre épuisée donne sa borne précise. Un ID
remplacé par une nouvelle fenêtre ne peut plus être réactivé. La création d'une
nouvelle fenêtre est une nouvelle allocation d'observation, pas un reset paper.

Bornes acceptées : durée 1–900 s, budget 8–200 appels HTTP/quotes, polls 1–300,
intervalle 1–30 s. L'arrêt se fait dès la première borne atteinte. Une requête déjà
engagée peut finir après l'échéance jusqu'à son timeout borné; le brut reste
reconstructible et aucune intention/règlement n'est appliqué hors fenêtre.

## Endpoint, curseur et recherche

- `ASTRA_OBSERVER_RPC_URL` est lu avec `os.environ` dans le processus Python lancé
  par CMD. `ASTRA_OBSERVER_NETWORK` doit être `mainnet`. Pas de substitution avec
  `SOLANA_RPC_URL` Devnet; pas de WebSocket ni de wallet requis pour ce suivi HTTP.
- `JUPITER_API_KEY` reste optionnelle selon les accès quotes existants. Valeurs
  secrètes non affichées. Le diagnostic donne la variable, sa présence, un libellé
  d'hôte public autorisé ou CUSTOM_HOST_REDACTED, et la preuve genesis Mainnet.
- `cursor_slot` = maximum du slot de quote d'entrée et des événements archivés
  du **même pool et mint**. Signature et horodatage indiqués sont ceux du dernier
  événement observé; `cursor_signature_slot` explicite leur propre slot.
- Requête : `getSignaturesForAddress(pool, {limit:32, commitment:"confirmed"})`.
  **Pas de before/until**, donc aucune inversion de ces paramètres. Le timestamp
  de réception n'est pas utilisé comme un faux timestamp on-chain.
- Les signatures réussies, non déjà hydratées, au-dessus du slot d'entrée et au
  moins au curseur de début de fenêtre sont candidates. Une signature inconnue
  au même slot que le curseur peut passer. Priorité au slot le plus récent.
- Une transaction par poll, au plus deux tentatives par signature. `getTransaction`
  conserve `maxSupportedTransactionVersion:1`. Les filtres et erreurs sont comptés.
- Recherche limitée à la tête de 32 signatures; ce n'est **pas** une preuve de
  couverture exhaustive ni un rattrapage paginé de tout l'historique.

## Diagnostic Windows sans secret

La console et `position-continuation/watch-report.json` exposent notamment :
`position_loaded`, `pool`, `mint`, `cursor_slot`, `cursor_signature`,
`cursor_availability_ns`, `network_attempted`, `signature_search_completed`,
`signatures_found`, `new_signatures_found`, `transactions_hydrated`,
`position_observations`, `latest_slot_seen`, `stop_reason`, appels/budget et rejets.
`signatures_found` compte les signatures distinctes de l'invocation;
`signature_rows_seen` compte les lignes reçues, répétitions incluses.

| Étape | Signification |
|---|---|
| NO_NETWORK_CALL | Aucune tentative réseau dans cette invocation; lire la borne/configuration. |
| NO_NEW_SIGNATURE | Aucune signature nouvelle admissible observée. Si recherche échouée, le résultat est FAIL et ne prouve pas une absence. |
| NEW_SIGNATURE_NOT_HYDRATED | Signature candidate, mais transaction non obtenue : délai, quota, réponse null, erreur ou retry épuisé. |
| NEW_TRANSACTION_UNSUPPORTED | Transaction reçue, sans nouvelle PositionHealth pour la position. Décodage/identités à examiner. |
| NEW_OBSERVATION_REJECTED | PositionHealth produite mais preuves/Risk refusés; raisons explicites. |
| NEW_POSITION_OBSERVATION | Nouvelle PositionHealth admissible; HOLD est valable, sans prétendre qu'un SELL a eu lieu. |

Les erreurs source restent FAIL avec leurs codes; l'absence de preuve reste
NOT_EXECUTED. `latest_slot_seen=null` n'est jamais présenté comme slot zéro.
Le diagnostic d'une invocation n'est pas gonflé par les compteurs des fenêtres
précédentes. Toutes les fenêtres restent dans le journal et `watch-review.json`.

## Validation et livraison

Les tests synthétiques sont explicitement des tests; aucun de leurs fills n'est
ajouté à la position réelle archivée. La migration de la référence et le replay
sont vérifiés sans réseau. Le watcher réel Windows/Mainnet reste NOT_EXECUTED.
`validate-all.cmd` demeure la gate complète; la nouvelle phase est le watcher
ciblé, mais il n'est pas nécessaire de relancer toute la gate pour surveiller.
Rapports et prochaine reprise : **watch_handoff/NEXT_SESSION.md**.
