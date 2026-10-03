# Premier round-trip paper — audit des preuves Windows all-validation-92dln067

## Conclusion

Le round-trip est **vérifié dans les artefacts fournis** et reconstruit hors réseau : deux intentions et deux règlements paper, sur VSOF/WSOL via PumpSwap. Aucun ordre ni achat/vente ASTRA exécuté sur Solana. Les signatures ci-dessous appartiennent aux transactions de marché observées, pas à des transactions du portefeuille paper.

**PnL paper net : −0,004358759 SOL.** Durée entre règlements paper : **8,2101692 s**. Notionnel d’achat : **0,01 SOL** ; frais fixes supposés : **0,0042 SOL** au total. Le PASS qualifie le fonctionnement/replay du scénario, pas sa rentabilité ni sa réalisabilité aux mêmes prix.

## Niveaux de preuve

- **PROVEN** : valeur directement présente dans un artefact fourni, cohérente avec ses hashes et références. Ce terme ne signifie pas une vérification indépendante du réseau ou de la finalité.
- **DERIVED** : calcul reproductible à partir de ces valeurs, avec unités et formule explicites. Les résultats paper restent conditionnels.
- **UNKNOWN / NOT_MEASURED** : aucune valeur attribuée sans preuve. Les hypothèses du modèle ne sont pas des coûts d’exécution réellement mesurés.

Le premier ZIP reçu était un ancien package documentaire. Il a été écarté comme preuve de ce trade. Cet audit utilise les JSON et SQLite joints ensuite, dont les SHA-256 sont listés dans `roundtrip_analysis.json`.

## Contrôles réalisés

- **PROVEN** : `validation-summary(3).json` indique win32 et `all-validation-92dln067`.
- **DERIVED — PASS** : intégrité SQLite raw/engine/paper, 47 frames brutes, chaînes de hashes, reconstruction des quatre décisions/résultats, état JSON identique aux SQLite et opportunités reconstituées depuis les réponses brutes.
- **DERIVED — PASS** : chaque quote et preuve utilisée est disponible avant son évaluation ; les deux quotes de règlement sont postérieures à leurs intentions et avancent de 15 slots, pour un minimum imposé de 1.
- Accès réseau bloqué pendant l’audit. Vérification finale des SHA-256 : aucun fichier d’entrée modifié. Aucun composant produit modifié ; pas de qualification relancée.

Head brut : `bb29188f0e97887095075f3c5def200480bbfe6fac81d2309140d31bbc36c4c4`.

## Actif et provenance de marché — PROVEN

- Métadonnées du mint : **VSOF**, 6 décimales. Le symbole provient des comptes RPC, pas d’un URI téléchargé.
- Mint : `HG5rCmkPpWyXvdQ1iytj3YwNg6vdzeb8srs2bzqNpump`.
- Quote : WSOL `So11111111111111111111111111111111111111112`, 9 décimales.
- Pool : `9fLTaEopbBu67oxCJvW2rdfcRVWsinFKKfX4VEwizDNJ`.
- Route Jupiter directe, 100 %, label `Pump.fun Amm`, même pool pour les huit quotes aller/retour.
- Token-2022 avec metadataPointer et tokenMetadata immuables, autorités mint/freeze absentes ; vault immutableOwner ; preuves de compte aux frames 17, 27, 35, 43.
- Engagement RPC : confirmed. Finalité et absence de réorganisation à posteriori non vérifiées indépendamment.

| Étape paper | Slot transaction observée | Instruction de marché | Signature observée |
|---|---:|---|---|
| BUY submit | 452325975 | sell | `2KHLt7Kx5ZkU7sgqmhP8vbcivVSJFTjjF3Ckwqj84sk2k8VFTCxSHDD75KTwEBQw4x68WD1LLbbBF5od21tuykCZ` |
| BUY settle | 452325981 | buy_exact_quote_in | `Tfp1J1fb8x5MNJWHZpy4h2acPL5YRKsyVcQPLMzqwx3RuLCqx2cWWRAd2dF6UZhrJptSaYDQx8Xcz9spyiSrXeP` |
| SELL submit | 452325993 | buy_exact_quote_in | `8kSRpyFRehWvVSvh5adJzEZZ8KBKp2N6Tci2XLkjXSbDZ6wCcFNiurRAhfnTbMisQobFLruUpCeEkHy6thW7TBN` |
| SELL settle | 452326011 | sell | `4WambDfnoaYnTV3yELKvFabDzHt4wKpyxhPHyDZ94fn5ekDFYqtRHTe9CsmpoL7TmPqbaQviimmfECRKg1TWhFnL` |

La première transaction observée est un SELL d’un tiers ; la stratégie de qualification propose néanmoins BUY. Il ne s’agit pas d’un système de copie des trades ni d’une stratégie d’alpha validée.

## Chronologie — timestamps archivés PROVEN, conversions/durées DERIVED

Horaires UTC. Heure de Paris : ajouter deux heures pour cette date (ex. 15:19:39 UTC = 17:19:39). La précision affichée reproduit le stockage ; elle ne prouve pas une horloge exacte à la nanoseconde.

| Étape | Date/heure UTC de décision ou règlement | Slot quote | Quote disponible à UTC |
|---|---|---:|---|
| BUY submit | 2026-10-01T15:19:39.271045600Z | 452325977 | 2026-10-01T15:19:37.142138900Z |
| BUY settle | 2026-10-01T15:19:43.367432500Z | 452325992 | 2026-10-01T15:19:41.227807400Z |
| SELL submit | 2026-10-01T15:19:47.479133100Z | 452326008 | 2026-10-01T15:19:45.333942800Z |
| SELL settle | 2026-10-01T15:19:51.577601700Z | 452326023 | 2026-10-01T15:19:49.463112000Z |

- Durée de détention paper, SELL règlement − BUY règlement : **8,2101692 s**.
- Première décision BUY → règlement SELL : **12,3065561 s**.
- Session totale mesurée par horloge monotone : **16,4152057 s** ; trois polls et trois hydratations de suivi, chacun produisant un événement compatible.
- Deux intentions, zéro rejet dans cette session, zéro position et zéro intention restantes. Couverture : sous-ensemble observé, non exhaustif.

## Quotes et prix — observations versus modèle

Les montants des quotes sont **PROVEN** comme réponses fournisseur archivées. Les prix unitaires et les décotes sont **DERIVED**. Une quote est indicative, pas un ordre exécuté.

| Étape | Entrée | Sortie annoncée | Minimum de sortie | Prix quote (SOL/VSOF) | Prix paper hors frais fixes (SOL/VSOF) |
|---|---:|---:|---:|---:|---:|
| BUY submit | 0.01 SOL | 0.408803 VSOF | 0.406759 | 0.024461660017 | 0.024584582025 |
| BUY settle | 0.01 SOL | 0.408782 VSOF | 0.406739 | 0.024462916665 | 0.024585790888 |
| SELL submit | 0.406739 VSOF | 0.009890467 SOL | 0.009841015 | 0.024316495345 | 0.024194913692 |
| SELL settle | 0.406739 VSOF | 0.009890694 SOL | 0.009841241 | 0.024317053442 | 0.024195469330 |

Les prix paper des lignes `submit` représentent seulement le seuil/modèle envisagé à la décision. **Seules les lignes `settle` créent un règlement paper**.

Formules : BUY = SOL engagés / tokens obtenus ; SELL = SOL obtenus / tokens vendus. Décimales contrôlées dans les quatre snapshots de comptes.

Quantité réellement comptabilisée dans le scénario : **406 739 unités brutes = 0,406739 VSOF**. Toute cette quantité est ensuite soldée. Aucun solde token restant.

### Frais, slippage et impact

- **PROVEN — configuration hypothétique** : 2 100 000 lamports = **0,0021 SOL par jambe**, soit 0,0042 SOL. Ce forfait regroupe un budget supposé réseau/ATA/priorité ; aucune de ces composantes n’a été mesurée pour un ordre ASTRA.
- Sortie paper = `min(otherAmountThreshold, floor(outAmount × 0,9975))`. Le modèle prévoit 25 bps de décote, mais le seuil de quote à 50 bps est ici le plus contraignant sur les deux règlements. Les deux décotes **ne sont pas additionnées**.
- BUY règlement : 408 782 → 406 739 unités, décote **49.977739 bps**.
- SELL règlement : 9 890 694 → 9 841 241 lamports, décote **49.999525 bps**.
- `priceImpactPct` fournisseur, interprété par le modèle en fraction : BUY décision 34.140997 bps ; BUY règlement 29.355476 bps ; SELL décision 29.952551 bps ; SELL règlement 29.666289 bps. Ce n’est pas un impact d’exécution ASTRA mesuré.
- À taille identique, quote BUY décision → règlement : 408 803 → 408 782 unités (−21). Quote SELL : 9 890 467 → 9 890 694 lamports (+227). Ces variations temporelles se distinguent de la décote paper ; elles ne permettent pas d’isoler marché, liquidité et frais.
- Détail des frais DEX inclus dans les outputs : **UNKNOWN**. `platformFee=null` est observé ; il ne prouve pas l’absence de tout coût. Les frais des transactions de tiers existent dans le brut mais ne sont pas imputés au portefeuille paper.

## Portefeuille et PnL — DERIVED, cohérents avec le ledger

| État | Cash SOL | VSOF | Intention en attente |
|---|---:|---:|---|
| Initial | 1,000000000 | 0 | aucune |
| Après intention BUY | 1,000000000 | 0 | BUY |
| Après règlement BUY | 0,987900000 | 0,406739 | aucune |
| Après intention SELL | 0,987900000 | 0,406739 | SELL |
| Après règlement SELL | 0,995641241 | 0 | aucune |

- Débit BUY : **0,0121 SOL** = 0,01 notionnel + 0,0021 forfait.
- Produit SELL avant forfait : **0,009841241 SOL** ; crédit net : **0,007741241 SOL**.
- **PnL brut avant forfaits fixes : −0,000158759 SOL** = 0,009841241 − 0,01. Ce « brut » inclut déjà les décotes simulées et les effets présents dans les quotes ; ce n’est pas un PnL avant tous frais DEX.
- **PnL net : −0,004358759 SOL** = 0,007741241 − 0,0121.
- Rendement net / notionnel 0,01 SOL : **−43,58759 %** ; / coût d’entrée 0,0121 SOL : **−36,02280165 %** ; / cash initial 1 SOL : **−0,4358759 %**.
- Les forfaits représentent 42 % du notionnel d’achat sur l’aller-retour. Ils expliquent l’essentiel de la perte simulée ; ce résultat ne démontre pas qu’un trade réel aurait subi les mêmes coûts.

## Risk et Evidence — PROVEN dans les enregistrements, réévalués hors réseau

Les quatre évaluations Risk indiquent `allowed=true`, raisons vides. Limites conservées : position 0,02 SOL, exposition 0,04 SOL, deux positions, réserve quote minimale 1 SOL, slippage maximal 100 bps, perte/session maximale 0,01 SOL, fraîcheur 5 s. Le montant d’entrée frais inclus (0,0121 SOL) est sous la limite de position.

Preuves par étape :

| Étape | Plan | Quote directe | Quote inverse | Comptes | Slot comptes | Réserve WSOL observée (SOL) |
|---|---:|---:|---:|---:|---:|---:|
| BUY submit | 18 | 15 | 16 | 17 | 452325984 | 20734.219414450 |
| BUY settle | 28 | 25 | 26 | 27 | 452326001 | 20734.219839400 |
| SELL submit | 36 | 33 | 34 | 35 | 452326015 | 20734.458044214 |
| SELL settle | 44 | 41 | 42 | 43 | 452326031 | 20734.458369551 |

Chaque jeu lie mint/pool/vault/programmes, réserve, autorités, taille et route directe/inverse. Les snapshots sont à des slots différents : ils ne forment pas une preuve atomique d’exécution. Une route inverse observable ne garantit pas sa disponibilité future.

## Latences et contrôle temporel

| Étape | Réception événement → décision/règlement (s) | Acquisition des preuves monotone (s) | Âge quote directe à l’évaluation (s) |
|---|---:|---:|---:|
| BUY submit | 2.3349248 | 2.3236588 | 2.1289067 |
| BUY settle | 3.5866551 | 3.5751546 | 2.1396251 |
| SELL submit | 2.8932300 | 2.8838428 | 2.1451903 |
| SELL settle | 2.9024764 | 2.8915535 | 2.1144897 |

- BUY : décision → quote ultérieure **1,9567618 s** ; quote → règlement **2,1396251 s** ; total **4,0963869 s**.
- SELL : décision → quote ultérieure **1,9839789 s** ; quote → règlement **2,1144897 s** ; total **4,0984686 s**.
- HTTP RPC : 16 échantillons ; p95=p99 **132,7599 ms**. Ce compteur RPC **exclut les transports HTTP des quotes**, conservés séparément dans les frames de quote.
- Notification → traitement : 2 échantillons ; p95=p99 **104,4175 ms**. Ce n’est pas une mesure du cycle paper complet : le transfert vers le suivi ciblé interrompt la mesure Observer du message déclencheur avant son ajout au compteur.
- HTTP quotes : 8 échantillons ; min **49,2857 ms**, max/p95 **73,7228 ms**, moyenne **55,5590 ms**, durées monotones archivées. La temporisation de 2,05 s entre appels quote appartient à l’acquisition globale, pas à ces RTT.
- `timeTaken` fournisseur présent dans les quotes : environ 0,13–0,21 ms. Valeur déclarée par le fournisseur, pas une mesure aller-retour réseau.
- Latence d’émission fournisseur et erreur/synchronisation de l’horloge : **NOT_MEASURED / UNKNOWN**. Les timestamps de décision/règlement sont pris avant la validation SQLite ; le moment exact de durabilité n’est pas enregistré séparément.

Les contrôles temporels rejoués n’ont trouvé aucune utilisation de preuve future à l’instant d’évaluation. Cette conclusion porte sur les horodatages archivés ; elle n’atteste pas l’exactitude absolue de l’horloge Windows.

## V1e live_provenance — analyse séparée

**Cause exacte du FAIL dans le rapport : `events=0`.** Les deux autres branches de la condition d’échec sont fausses : `source_complete=true`, `decoder_errors=0`.

- Plage : **506315883–506315888**, six slots attendus, six archivés/résolus/comptabilisés.
- Erreurs, unresolved, exclusions et slots sautés : **0**. `transactions_expected=137`.
- `unique_event_publications=0`, `fully_decoded=false` ; zéro erreur de hash/replay et de clé étrangère, intégrité OK.
- Reconstruction hors réseau identique et reprise dans un nouveau processus rapportées.
- Dataset SHA-256 : `d3e3bda27cc4546c2f0972072462a914d7037e7da502dc05cae364e9601abcfb`.

Il s’agit donc d’une plage sans événement **reconnu par ce décodeur**, pas d’une couverture source absente selon ces preuves. Le FAIL du critère métier reste valide. Cela ne prouve pas que les 137 transactions ne contiennent absolument aucun transfert : les blocs SQLite/dataset V1e ne sont pas fournis pour examiner indépendamment tous les cas non pris en charge. Aucun défaut de décodage n’est signalé, mais son absence absolue ne peut être prouvée par les seuls compteurs.

Les autres SQLite joints sont des archives/moteurs Observer ; ils ne contiennent pas la base de blocs de cette plage V1e. Leurs tables ne permettent donc pas un second décodage de ces 137 transactions. Ce FAIL est indépendant du round-trip Mainnet vérifié.

## Ce qui manque pour mesurer les prochaines sessions correctement

1. **Coûts** : modèle détaillé/versionné distinguant réseau, priorité, ATA/création/fermeture, frais DEX et frais de plateforme ; expliquer chaque hypothèse et éviter de facturer systématiquement une création d’ATA à chaque jambe.
2. **Exécutabilité** : quotes à taille donnée ne suffisent pas à établir probabilité de fill, coûts d’échec, MEV, inclusion ou maintien de la route. Ces éléments restent UNKNOWN ; ne pas les remplacer par un fill certain.
3. **Latences** : instrumenter séparément réception WS, hydratation, début/fin des quotes, comptes, décision, commit durable et mise à jour portefeuille ; inclure le message déclenchant le changement de phase ; conserver durées monotones et qualité de synchronisation horloge.
4. **Finalité/provenance** : suivre confirmation/finalisation et réorganisations, conserver identités de requête, versions fournisseur, slots et timestamps d’acquisition pour toutes les preuves.
5. **Échantillonnage** : plusieurs sessions, refus et opportunités manquées, états ouverts et échecs de sortie ; le suivi ciblé met la découverte globale en pause. Un seul cycle réussi ne mesure pas la qualité d’une stratégie.
6. **PnL** : conventions brut/net explicites, lots/cost basis, valorisation des positions ouvertes et FX horodaté si des résultats USD sont souhaités. Aucun USD PnL dérivé des champs indicatifs swapUsdValue seuls.
7. **V1e** : joindre la base de blocs/dataset de la plage exacte si l’objectif est de vérifier les instructions non reconnues, en plus des compteurs déjà suffisants pour expliquer la branche du FAIL.

Aucune de ces instrumentations n’a été implémentée pendant cet audit. Aucun composant qualifié modifié. Les valeurs exactes, signatures, hashes, quotes, quatre enregistrements ledger et contrôles détaillés sont fournis dans `roundtrip_analysis.json`.
