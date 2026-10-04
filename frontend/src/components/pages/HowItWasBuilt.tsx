import { Link, Tile } from '@carbon/react';
import { REPO_URL } from '../AppSideNav';

interface Service {
  name: string;
  what: string;
  here: string;
  why: string;
}

// The IBM services Archer runs on. Kept in one list so the cards stay
// consistent with each other.
const SERVICES: Service[] = [
  {
    name: 'IBM watsonx.ai',
    what: "IBM's platform for building with generative AI, with a catalogue of foundation models available to call on demand.",
    here: 'Every question goes to a model on watsonx.ai. It works out what you are asking, writes the database query, explains answers in plain English and summarises results.',
    why: 'Enterprise controls over which models are used and how, a choice of models, and pay-per-use pricing with no monthly fee on the Essentials plan.',
  },
  {
    name: 'IBM Code Engine',
    what: 'A fully managed platform that runs applications in containers without anyone having to manage servers.',
    here: 'Runs the whole of Archer: the web page you are using and the service behind it.',
    why: 'It scales to zero when nobody is using the demo, so idle time costs nothing, and starts again automatically when someone visits.',
  },
  {
    name: 'IBM Container Registry',
    what: 'Private storage for the packaged versions of an application.',
    here: 'Every change to Archer is packaged and stored here, then Code Engine runs the newest version.',
    why: "It sits in the same IBM Cloud account as everything else, keeps the packages private, and the free tier is enough for a demo.",
  },
];

export function HowItWasBuilt() {
  return (
    <article className="archer-page__body">
      <p className="archer-page__eyebrow">About this demo</p>
      <h1 className="archer-page__title">How Archer was built</h1>
      <p className="archer-page__lead">
        Archer lets anyone ask questions about sales data in plain English and
        get an answer they can check in about a second, with no SQL, no report
        requests and no waiting for an analyst. It shows what a business can
        build on IBM technology, and how quickly.
      </p>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">The problem it solves</h2>
        <p>
          Most sales questions are simple to ask and slow to answer. Someone
          wants to know which partners grew last quarter or how many deals
          included services, and the answer sits in a database that only a few
          people can query. Archer puts that database behind a conversation.
        </p>
        <p>
          Every answer shows the query that produced it, so the figure can be
          checked. You can ask follow-ups such as &quot;what about the second
          one?&quot;, ask it to explain an answer, or ask several things at
          once.
        </p>
      </section>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">Built with IBM Bob</h2>
        <p>
          The first version of Archer was built with IBM Bob, IBM&apos;s AI
          development partner. Bob works inside the developer&apos;s editor and
          handles much of the software lifecycle: understanding existing code,
          planning a change, writing and testing it, and documenting the
          result.
        </p>
        <p>A project like this one comes together with Bob in a few steps:</p>
        <ol className="archer-page__steps">
          <li>
            <strong>Describe the goal.</strong> In Ask mode, Bob reads the
            existing code and answers questions about it without changing
            anything, so the starting point is clear.
          </li>
          <li>
            <strong>Plan it.</strong> In Plan mode, Bob turns the idea into a
            technical plan: which pieces are needed, how they fit together, and
            what to build first.
          </li>
          <li>
            <strong>Build it.</strong> In Agent mode, Bob writes and changes the
            code, asking for approval before each step, so the developer stays
            in control.
          </li>
          <li>
            <strong>Test and refine.</strong> Bob runs the tests, reads the
            results and iterates until the feature works.
          </li>
        </ol>
        <p>
          For a team that needs a working demo quickly, that is the value: one
          person can go from an idea to a running application on IBM Cloud
          without a full development team, and the governance and security
          controls an enterprise expects come built in.
        </p>
      </section>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">The IBM services behind it</h2>
        <div className="archer-page__cards">
          {SERVICES.map((service) => (
            <Tile key={service.name} className="archer-page__card">
              <h3 className="archer-page__card-title">{service.name}</h3>
              <p className="archer-page__card-what">{service.what}</p>
              <dl className="archer-page__card-facts">
                <div>
                  <dt>In Archer</dt>
                  <dd>{service.here}</dd>
                </div>
                <div>
                  <dt>Why it was chosen</dt>
                  <dd>{service.why}</dd>
                </div>
              </dl>
            </Tile>
          ))}
        </div>
      </section>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">The results</h2>
        <dl className="archer-page__figures">
          <div>
            <dt>98.4%</dt>
            <dd>of 61 test questions answered correctly, measured by running every query</dd>
          </div>
          <div>
            <dt>About 1 second</dt>
            <dd>typical time to an answer, once the demo is running</dd>
          </div>
          <div>
            <dt>Under a tenth of a penny</dt>
            <dd>the model cost of a typical question</dd>
          </div>
          <div>
            <dt>£0 when idle</dt>
            <dd>the demo scales to zero between visitors</dd>
          </div>
        </dl>
      </section>

      <p className="archer-page__note">
        Archer is a demonstration over synthetic data. The technical detail,
        from the architecture to how accuracy is measured, is in the{' '}
        <Link href={REPO_URL} target="_blank" rel="noopener noreferrer">
          documentation on GitHub
        </Link>
        .
      </p>
    </article>
  );
}
