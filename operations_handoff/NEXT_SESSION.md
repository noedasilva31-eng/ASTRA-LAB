# Point de reprise exact

Workspace livré : ASTRA-V1-operations. La baseline ASTRA-V1-integrated et les
références V1b/V1c/V1d n'ont pas été remplacées. Le rapport Windows fourni (189 tests,
seul live_memory sans témoin) figure dans ce dossier, distinct des résultats locaux.

Réalisé dans cette session :
- correctif V1d/live_memory par preuve réelle sélectionnée/recherche bornée ;
- journal d'alertes persistant branché à run/poll ;
- timeline de connaissances et features par slot, cutoff séquentiel, reprise,
  déduplication, restauration et replay ;
- adaptateur PumpSwap courant, six instructions / cinq types d'événements,
  événements self-CPI directs, exports et intégration à la timeline ;
- tests et gate racine étendus, aucune nouvelle baseline Windows revendiquée.

Première action d'intégration sur Windows avec l'environnement RPC existant :
`validate-all.cmd`. Conserver les preuves `memory_validation/memory-report-*`.
La gate échoue si aucune vraie preuve SOL n'est obtenue dans les bornes ; ne pas
retirer cette exigence. L'environnement Work n'avait pas d'endpoint configuré.
Les tests DEX synthétiques restent distincts d'une qualification protocole réelle.

Première action de développement : ajouter un témoin PumpSwap réel archivé et
vérifiable du format épinglé (ou caractériser son format historique exact), le
rejouer avec `python -m astra_dex ... --require-event`, et tester son intégration
au dataset/timeline. La collecte actuelle est Devnet : ne pas ouvrir silencieusement
Mainnet ni prétendre qu'une plage Devnet sans PumpSwap le qualifie. Tout nouvel
accès réseau doit conserver quotas, bornes et archive avant transformation.
Si ce témoin n'est pas accessible, poursuivre localement le contrat Paper/Risk
et la séparation Hot Path sans simuler la preuve réelle manquante.

Ensuite : features temporelles agrégées à partir des événements DEX ; contrat de
cotation/slippage/frais ; moteur paper et journal auditable, fills postérieurs à la
décision avec connaissances coupées à son reçu ; Risk déterministe borné ; puis
CPI routés, wallets/holders et qualification opérationnelle selon dépendances.
Aucun ordre LIVE, aucune promotion autonome de candidat n'est autorisé par le code
livré. Ne pas confondre mouvement de soldes, volume de marché et prix exécutable.

Consulter FUNCTIONAL_SPRINT.md pour les périmètres exacts et CHECKLIST.json pour
les preuves PASS/FAIL de cette exécution. Les anciens NEXT_SESSION dans les dossiers
de handoff sont historiques. La gate unique reste validate-all.cmd ; utiliser des
tests ciblés pendant le développement, puis la non-régression complète au jalon.
