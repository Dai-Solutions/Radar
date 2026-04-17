# Tasks for Backend & Scoring Enhancements

- [x] **Phase 1: Foundation & Refactoring**
    - [x] Decouple `CreditScorer` from DB session for core math logic (Pure Math Service)
    - [x] Add `Standard Deviation` (Volatility) calculation to `AgingAnalyzer`
    - [x] Implement DSCR (Debt Service Coverage Ratio) fields and calculation

- [x] **Phase 2: Mathematical Refinement**
    - [x] Update `CreditScorer` with Weighted Volatility penalty
    - [x] Implement Sector-Specific Z-Score constants (Retail, Service, Manufacturing)
    - [x] Update `vade` (tenor) recommendation logic with risk-adjusted volatility

- [x] **Phase 3: Probabilistic Engine**
    - [x] Implement Monte Carlo simulation for "What-If" scenarios
    - [x] Update `ScenarioResult` to use real probabilistic data

- [x] **Phase 4: Security & Performance**
    - [x] Add custom `request_limit` decorator for credit request end-point
    - [x] Implement time-based caching for global settings in `app.py`
    - [x] Add global exception handlers and branded error pages

- [/] **Phase 6: Mathematical Visibility & UI Finalization**
    - [ ] Refine `CreditScorer._create_assessment` with DSCR/Volatility logic
    - [ ] Update `ResultWrapper` in `app.py` to pass new metrics
    - [ ] Modernize `rapor.html` with new visualization components

- [ ] **Phase 5: Verification & Walkthrough**
    - [ ] run Unit Tests for all scoring components
    - [ ] Manual verification via UI
    - [ ] Create Walkthrough artifact
