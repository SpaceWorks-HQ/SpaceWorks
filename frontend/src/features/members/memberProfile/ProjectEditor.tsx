import { ImageUploader } from "../../staff/ImageUploader";
import { profileToneForIdentity } from "./helpers";
import { type ProjectDraft } from "./types";

export function ProjectEditor({
  makerspaceId,
  project,
  imageUrl,
  onChange,
  onRemove,
  onImageChanged,
}: {
  makerspaceId: number;
  project: ProjectDraft;
  imageUrl: string | null;
  onChange: (next: ProjectDraft) => void;
  onRemove: () => void;
  onImageChanged: () => void;
}) {
  return (
    <div className={`rounded-lg border ${profileToneForIdentity(project.id)} p-3`}>
      <input
        className="desk-input w-full"
        placeholder="Project title"
        aria-label="Project title"
        value={project.title}
        onChange={(event) => onChange({ ...project, title: event.target.value })}
      />
      <textarea
        className="desk-input mt-2 w-full"
        rows={2}
        placeholder="What is it?"
        aria-label="Project description"
        value={project.description}
        onChange={(event) => onChange({ ...project, description: event.target.value })}
      />
      {/* An image can only be attached to a project that exists server-side — a new one
          has no id to attach it to, so it appears after the first save. */}
      {project.id ? (
        <div className="mt-3">
          <ImageUploader
            endpoint={`/member/makerspaces/${makerspaceId}/profile/image`}
            currentUrl={imageUrl}
            label="Project image"
            extraBody={{ project_id: project.id }}
            clearQuery={`?project_id=${project.id}`}
            onChanged={onImageChanged}
          />
        </div>
      ) : (
        <p className="mt-2 text-xs text-muted">Save the project to add an image.</p>
      )}
      <div className="mt-2 space-y-2">
        {project.links.map((link, index) => (
          <div key={index} className={`flex flex-col gap-2 border-l-2 ${profileToneForIdentity(`${link.label}|${link.url}`)} p-2 sm:flex-row`}>
            <input
              className="desk-input w-full sm:w-40"
              placeholder="Label"
              aria-label="Link label"
              value={link.label}
              onChange={(event) =>
                onChange({
                  ...project,
                  links: project.links.map((row, position) =>
                    position === index ? { ...row, label: event.target.value } : row,
                  ),
                })
              }
            />
            <input
              className="desk-input w-full"
              placeholder="https://…"
              aria-label="Link URL"
              value={link.url}
              onChange={(event) =>
                onChange({
                  ...project,
                  links: project.links.map((row, position) =>
                    position === index ? { ...row, url: event.target.value } : row,
                  ),
                })
              }
            />
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-2">
        <button
          className="desk-button-ghost"
          type="button"
          onClick={() =>
            onChange({ ...project, links: [...project.links, { label: "", url: "" }] })
          }
        >
          Add link
        </button>
        <button className="desk-button-danger" type="button" onClick={onRemove}>
          Remove project
        </button>
      </div>
    </div>
  );
}
