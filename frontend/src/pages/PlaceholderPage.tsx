interface PlaceholderPageProps {
  title: string
  description: string
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <section aria-labelledby="page-title" className="space-y-2">
      <h1 id="page-title" className="text-lg font-semibold">
        {title}
      </h1>
      <p className="text-sm text-muted-foreground">{description}</p>
    </section>
  )
}
