# 010-approval-ux tasks

- [x] T1 [R1, AC1] Implement a prompt-toolkit approval selector with numbered
  choices, arrow-key navigation, safe deny default, and a details loop while
  retaining the injectable legacy reader.
- [x] T2 [R2, AC2] Emit an `approval_decided` Trace event from the Agent with
  outcome and policy metadata but without tool arguments.
- [x] T3 [R1, R2, AC1, AC2] Add terminal and runtime Trace tests, update the
  terminal capability document, and run the required verification commands.
