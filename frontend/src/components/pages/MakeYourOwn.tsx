import { Link } from '@carbon/react';
import { REPO_URL } from '../AppSideNav';

const GUIDE_URL = `${REPO_URL}/blob/main/docs/make-your-own.md`;

interface Step {
  title: string;
  body: string;
  detail?: string[];
}

// A summary of docs/make-your-own.md, which holds the commands and the full
// detail. Keep the two in step.
const STEPS: Step[] = [
  {
    title: 'Fork it and run it as it is',
    body: 'Archer is open source under the Apache 2.0 licence. Fork the repository on GitHub, clone it, and run the original on your own machine before changing anything, so any later problem is in your changes.',
  },
  {
    title: 'Set up watsonx.ai',
    body: 'Create an IBM Cloud account and a watsonx.ai Runtime service on the Essentials plan, which charges per use with no monthly fee. Create a watsonx.ai project, connect the Runtime service to it, then copy the project ID and create an API key.',
    detail: [
      'Put the API key and project ID in the .env file, with a login of your choosing and a few random secret keys.',
      'Archer then answers questions on your machine.',
    ],
  },
  {
    title: 'Point it at your own data',
    body: 'Archer queries one table in a SQLite database. Export the table you want to ask about, set its name in one place, and describe each column in plain English.',
    detail: [
      'The descriptions appear in the in-app guide and help the model understand your data.',
      'A few details tied to the sample sales data, such as the £ sign on revenue, are listed in the guide for you to change.',
    ],
  },
  {
    title: 'Teach the prompts your business',
    body: "Five prompt files tell the model how to behave. Most of the work is in the one that writes SQL: it needs your table's columns, the values inside them, what your business words mean in SQL, and worked examples of real questions.",
    detail: [
      'The planner, which reads each question in context, needs a description of your domain and example exchanges.',
      'The chat prompt needs its description of what your assistant can do.',
      'The retry and summary prompts usually work as they are.',
    ],
  },
  {
    title: 'Write test questions',
    body: "Replace the test questions with your own, each with a query you have checked by hand. The suite runs them all against the model and reports how many come back right, so you know whether a prompt change helped. A full run costs a few pence.",
  },
  {
    title: 'Deploy it on IBM Cloud',
    body: 'Create a Code Engine project, a Container Registry namespace and the two secrets Archer needs, then push a first version. Connect your GitHub repository with an API key and a few settings, and every change you merge goes live automatically.',
  },
  {
    title: 'Check it before you share it',
    body: 'Change the login, set a daily limit on how many questions are answered, use real signing keys, and remember that anyone with the login can ask anything your table holds.',
  },
];

export function MakeYourOwn() {
  return (
    <article className="archer-page__body">
      <p className="archer-page__eyebrow">Open source</p>
      <h1 className="archer-page__title">Make your own Archer</h1>
      <p className="archer-page__lead">
        Archer is built to be reused. Point it at your own data and it becomes
        a plain-English assistant for your business, running on your own IBM
        Cloud account.
      </p>
      <p>
        These are the steps, in order. The{' '}
        <Link href={GUIDE_URL} target="_blank" rel="noopener noreferrer">
          full guide on GitHub
        </Link>{' '}
        has every command and file to change.
      </p>

      <ol className="archer-page__journey">
        {STEPS.map((step) => (
          <li key={step.title}>
            <h2 className="archer-page__step-title">{step.title}</h2>
            <p>{step.body}</p>
            {step.detail && (
              <ul className="archer-page__detail">
                {step.detail.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">What you need</h2>
        <ul className="archer-page__detail">
          <li>An IBM Cloud account, with watsonx.ai on the Essentials plan.</li>
          <li>A GitHub account, for your fork and automatic deployment.</li>
          <li>Your data in one table, exported to SQLite.</li>
          <li>Python, Node and Docker on your machine.</li>
        </ul>
        <p>
          At the volumes a demo sees, the running cost is pennies a day. The
          model is the only part charged per use, and the application costs
          nothing while nobody is using it.
        </p>
      </section>

      <p className="archer-page__note">
        <Link href={GUIDE_URL} target="_blank" rel="noopener noreferrer">
          Read the full guide on GitHub
        </Link>
      </p>
    </article>
  );
}
