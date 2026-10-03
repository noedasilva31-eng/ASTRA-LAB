# Diagnostic fondé sur bridge-proofs.zip — Windows all-validation-w7abid48

Archive ZIP fournie : SHA-256
`b85d152aefa43a19451e700d4ba10333f14193f4eb5488235436b0b07e09982f`.
La base brute originale est conservée sans transformation dans
`bridge_tests/fixtures/windows-w7abid48.sqlite`. Son SHA-256 est figé dans
`astra_bridge/archived_check.py`. Les 58 frames ont passé l'audit de chaîne.
Head : `5390b8c66da3e8a80133ab40adcd3735f0f2fdd8b9b170ea75930c57e6aa5cb6`.
Les anciens résultats ne sont ni réécrits ni présentés comme des décisions nouvelles.

## unsupported_quote_currency : preuve exacte

Plans aux frames 28, 33 et 38 : base_mint = WSOL
`So11111111111111111111111111111111111111112` ; quote_mint respectivement :

- `F68dKQHnWemwGnv9rqrKYCLJRKFLQYLqBZzpS27n428a`
- `GvXGwgg2xkT6f5SQE7ZPoyhw5mZTD1i4VbJMMfS69oc3`
- `5iaPAawjunCwU8x763emo8CA1UJ2YdnSyJQdRXfhMqUD`

Ces adresses ne sont pas WSOL. Aucun symbole ni équivalence monétaire n'est inféré.
La présence de WSOL en base ne rend pas la cotation du pool libellée en SOL.
Le portefeuille et les limites monétaires de cette verticale utilisent WSOL en
quote. Inverser les événements supposerait aussi de renormaliser features, unités,
provenance et comptabilité. Ce travail dépasse ce correctif ciblé : REJECT conservé.
Cela ne signifie pas que les pools sont illégitimes ou malveillants.

La capture s'est arrêtée à 12 notifications (6 événements décodés, 5 plans uniques).
La qualification du bridge autorise désormais au maximum 64 notifications sur
120 secondes, avec le même budget persistant de 200 tentatives. Les orientations
incompatibles restent dans le census et ne déclenchent pas de quotes. Le code
Observer n'est pas modifié. Aucun événement absent n'est compté comme compatible.

## unsupported_token_program : preuve exacte

Réponses getMultipleAccounts, frames 10 et 51 : les deux mints de base sont détenus
par `TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb` (Token-2022), executable=false.

- `Bd9thw3PAeyHeBGSi4R1ARBuptpG5rM4fhB8BRWJkq1e` (métadonnées : glungus)
- `mLWY3TjoiPabqYYTeqFFjxDwtN4UZZoco3zrV1Spump` (métadonnées : UDR)

Les deux ont mintAuthority=null, freezeAuthority=null, isInitialized=true,
et exactement les extensions suivantes : metadataPointer (authority=null,
metadataAddress=mint) et tokenMetadata (updateAuthority=null, mint lié au compte).
Les vaults de base ont le même programme Token-2022 et uniquement immutableOwner.
Les mints/vaults de quote sont WSOL / programme SPL classique.

L'ancien rejet venait donc de la restriction TOKEN classique, pas d'un compte
exécutable ni d'une autorité de mint/freeze active.

## Support strict ajouté

Module isolé `astra_bridge/tokens.py`, profil
`token2022-immutable-self-metadata-v1`. Autorise uniquement la combinaison observée :
metadataPointer + tokenMetadata immuables et auto-liés ; vault immutableOwner.
Vérifie programme, parseur, compte non exécutable, identités mint/vault, structure,
absence d'autorités et cohérence du programme vault/mint. Conserve les contrôles
précédents sur état, propriétaire, délégation, close authority, réserves et fraîcheur.

Tout programme inconnu, extension supplémentaire/dupliquée/absente, metadata mutable
ou externe, transfer hook, transfer fee, permanent delegate, default account state,
pausable ou vault différent reste refusé. Aucun URI de métadonnées n'est téléchargé.
Les profils et programmes acceptés figurent dans la preuve liée au hash de la réponse.

Sources officielles consultées pour la sémantique des extensions :
- https://solana.com/docs/tokens/extensions/metadata
- https://solana.com/docs/tokens/extensions/immutable-owner

## Réévaluation hors réseau — pas de qualification live nouvelle

Plan 11 : le profil token passe, mais les quotes 8/9 échouent encore sur
`price_impact_limit`. Seuil Risk inchangé. Aucun fill ni intention admise.

Plan 52 : profil token, quotes 49/50, comptes 51 et dates originales satisfont les
preuves et le Risk inchangés. Une base paper TEMPORAIRE enregistre une intention
conditionnelle de réévaluation (BUY de 10 000 000 unités WSOL). Aucun règlement,
position, changement de cash ou PnL. Ce n'est pas un achat effectué historiquement.

Le contrôle `archived_real_accounts_and_risk` vérifie automatiquement ces résultats
sur le brut réel fourni, son hash, les décisions et l'absence de fill. Il ne remplace
pas `real_evidence_bridge` ou `real_conditional_roundtrip`. Un round-trip réel reste
NOT_EXECUTED en l'absence de nouvelles preuves compatibles et ultérieures.

Le FAIL historique V1e live_provenance lié à la plage n'est pas attribué au bridge
et ne reçoit aucune modification dans ce correctif.
