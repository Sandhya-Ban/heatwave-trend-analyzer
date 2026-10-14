export default function Insights({ items }) {
  const rest = items.filter((i) => i.level !== "headline");
  return (
    <ul className="insights">
      {rest.map((i, k) => (<li key={k} className={`ins-${i.level}`}>{i.text}</li>))}
    </ul>
  );
}
