# Photo Album backend (HW3)

- lambdas/index-photos   LF1, S3 PUT trigger -> Rekognition + custom labels -> OpenSearch
- lambdas/search-photos  LF2, GET /search -> Lex V2 -> OpenSearch -> presigned URLs
- tests/                 offline unit tests (python -m pytest tests -q)
- buildspec.yml          CodeBuild spec used by pipeline P1
- cloudformation/        T1 (template.yaml is generated: python cloudformation/build_template.py)
- lex/SearchIntent.md    Lex bot slot type and utterances
