// Mirrors backend/app/models.py — kept hand-in-sync deliberately rather than
// codegen'd, since the surface is small and stable.

export type JobStatus = "queued" | "processing" | "done" | "failed";
export type LeadStatus = "queued" | "processing" | "done" | "failed";

export interface Lead {
  id: string;
  job_id: string;
  source_file: string;
  thumbnail_url: string | null;
  first_name: string | null;
  last_name: string | null;
  job_title: string | null;
  company: string | null;
  location: string | null;
  phone: string | null;
  email: string | null;
  additional_phones: string[];
  website: string | null;
  raw_text: string | null;
  confidence: number;
  warnings: string[];
  status: LeadStatus;
  error: string | null;
  vlm_backend_used: string | null;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  status: JobStatus;
  total_files: number;
  completed_files: number;
  failed_files: number;
  created_at: string;
  updated_at: string;
  expires_at: string;
  leads: Lead[];
}

export interface JobSummary {
  id: string;
  status: JobStatus;
  total_files: number;
  completed_files: number;
  failed_files: number;
  created_at: string;
  updated_at: string;
}

export interface LeadUpdate {
  first_name?: string | null;
  last_name?: string | null;
  job_title?: string | null;
  company?: string | null;
  location?: string | null;
  phone?: string | null;
  email?: string | null;
  website?: string | null;
}

export interface HealthResponse {
  status: string;
  active_vlm_backend: string | null;
  primary_backend_healthy: boolean;
  fallback_backend_healthy: boolean;
  version: string;
}

export const EDITABLE_LEAD_FIELDS = [
  "first_name",
  "last_name",
  "job_title",
  "company",
  "location",
  "phone",
  "email",
] as const;

export type EditableLeadField = (typeof EDITABLE_LEAD_FIELDS)[number];
