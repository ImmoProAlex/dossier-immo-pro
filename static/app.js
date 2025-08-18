(function() {
  const $ = (sel) => document.querySelector(sel);

  const form = $("#calc-form");
  const result = $("#result");
  const rates = $("#rates");

  function payloadFromForm() {
    const v = (id) => document.getElementById(id).value;
    const coBorrowerStatus = v("b2_status");
    const hasCo = coBorrowerStatus !== "aucun";

    return {
      project: {
        property_price: parseFloat(v("property_price")),
        property_type: v("property_type"),
        personal_contribution: parseFloat(v("personal_contribution")),
        loan_duration: parseInt(v("loan_duration"), 10)
      },
      household: {
        main_borrower: {
          employment: {
            status: v("b1_status"),
            net_monthly_income: parseFloat(v("b1_income")),
            years_experience: parseFloat(v("b1_years")),
            trial_period: false
          },
          age: parseInt(v("b1_age"), 10)
        },
        co_borrower: hasCo ? {
          employment: {
            status: v("b2_status"),
            net_monthly_income: parseFloat(v("b2_income")),
            years_experience: parseFloat(v("b2_years")),
            trial_period: false
          },
          age: parseInt(v("b2_age"), 10)
        } : null,
        children: parseInt(v("children"), 10),
        current_rent: 0,
        other_monthly_credits: parseFloat(v("other_credits")),
        city: "Paris"
      }
    };
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    result.style.display = "none";
    try {
      const resp = await fetch("/api/evaluate", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(payloadFromForm())
      });
      const data = await resp.json();
      const lines = [
        `Score: ${data.score}/100 (${data.rating || "—"})`,
        `Mensualité (estimée): ${data.monthly_payment ? (Math.round(data.monthly_payment*100)/100)+' €' : '—'}`,
        `Endettement: ${data.debt_ratio ? (Math.round(data.debt_ratio*100)/100)+' %' : '—'}`,
        data.recommendations ? `Recommandations: ${data.recommendations.join(" | ")}` : "",
        data.application_id ? `Application ID: ${data.application_id}` : "",
        data.application_id ? `PDF (si payé): /api/dossier/${data.application_id}/pdf` : ""
      ].filter(Boolean);
      result.textContent = lines.join("\\n");
      result.style.display = "block";
      window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"});
    } catch(err) {
      result.textContent = "Erreur: " + (err?.message || err);
      result.style.display = "block";
    }
  });

  $("#show-rates").addEventListener("click", async () => {
    rates.style.display = "none";
    try {
      const resp = await fetch("/api/taux-actuels");
      const data = await resp.json();
      const src = data.source || data.rate_source || "—";
      const dt = data.date_maj || data.rate_last_update || "—";
      rates.textContent = "Taux: " + JSON.stringify(data.taux || data.rates || data, null, 2) + "\\nSource: " + src + "\\nDernière mise à jour: " + dt;
      rates.style.display = "block";
    } catch(err) {
      rates.textContent = "Erreur: " + (err?.message || err);
      rates.style.display = "block";
    }
  });
})();
