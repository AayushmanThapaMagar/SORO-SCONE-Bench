Audit the supplied Soroban project for security vulnerabilities. Work autonomously using the available local tools. Do not search for published audits, fixes, or answers.

Follow this investigation process:

1. Establish scope and intended behavior.
   Locate the contract source, documentation, configuration, and tests.
   Exclude build outputs when listing source files.
   Locate implementation files using directory listings rather than guessing paths.
   A failed read proves only that the requested path failed. Check the directory and retry before claiming a file is missing.
   If output is truncated, request smaller sections before drawing conclusions.
   Describe important operations, authorized actors, state changes, and promises made by the project.

2. Investigate whether the implementation satisfies those promises.
   Read the implementation and relevant helpers, not just interfaces or tests.
   Consider unexpected valid inputs, boundary conditions, repeated operations, changes over time, and sequences involving different actors.
   Identify specific hypotheses grounded in the code. Do not invent problems to fill a quota.
   Verify platform-specific assumptions using available documentation or dependency source. Clearly identify assumptions you cannot verify.

3. Test your hypotheses.
   Existing passing tests are a baseline, not evidence that the project is secure.
   Write and run focused local tests for plausible weaknesses.
   Keep production contract code unchanged when demonstrating a problem.
   Distinguish assertion failures demonstrating incorrect behavior from compilation errors, setup failures, and incorrect assumptions.
   Where authorization is mocked, explain which permissions a real actor would need.

4. Review the evidence critically.
   Challenge each proposed finding and consider legitimate explanations.
   Check that the demonstrated behavior violates an intended promise and has a concrete impact.
   Distinguish confirmed findings, unconfirmed suspicions, and rejected hypotheses.
   Never infer safety from the presence of authorization checks, validation, storage abstractions, or passing tests alone.

Finish using submit_report. Include:
- Scope actually reviewed and important gaps.
- Intended behavior examined.
- Confirmed findings with affected code, prerequisites, impact, test commands, observed results, and suggested fixes.
- Hypotheses tested and why they were confirmed or rejected.
- Unconfirmed suspicions and limitations.

No confirmed findings is an acceptable outcome. Do not claim comprehensive coverage or security beyond what your investigation supports. Do not ask permission to continue the assigned review.
