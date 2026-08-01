export default function DashboardLoading() {
  return (
    <main className="dashboard-page" aria-busy="true">
      <div className="dashboard-loading-header" />
      <div className="dashboard-shell">
        <section className="dashboard-loading-heading">
          <span />
          <span />
          <span />
        </section>
        <div className="dashboard-loading-filters" />
        <section className="dashboard-loading-list" aria-label="Loading repositories">
          {Array.from({ length: 5 }, (_, index) => (
            <div key={index}>
              <span />
              <span />
              <span />
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
