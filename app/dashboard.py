"""Streamlit QA-inspector dashboard.

Run:  streamlit run app/dashboard.py

Screens (blueprint section 15):

    Lot Overview           lot cards: part count, flagged %, PDA status
                           (green/amber/red), mean risk score; alert when a lot
                           exceeds PDA
    Part Table             sortable and filterable by risk score, verdict, lot,
                           parameter; colour-coded verdict chips; click to
                           drill down
    Part Detail            the drift plot with lot envelope and forecast; risk
                           score breakdown bar; reason codes; measured values
                           against lot medians; download screening report
    Distribution Explorer  per-parameter histogram on log and linear axes with
                           DPAT limits and datasheet limits overlaid, flagged
                           part highlighted
    Model Performance      confusion matrix, recall-vs-overkill curve, PR
                           curve, Module B predicted-vs-actual scatter, MAE
                           table
    Decision Policy        the C_FN:C_FP cost-ratio slider with live threshold
                           and live recall/overkill readout. The demo
                           centrepiece - dragging it from 1:1 to 100:1 and
                           watching recall climb is the most persuasive fifteen
                           seconds available.
    Wafer Map (optional)   die grid coloured by risk score, showing spatial
                           clustering

Renders only. All scoring comes from src.fusion and src.evaluate; no metric is
computed in this file.

TODO: implement.
"""
