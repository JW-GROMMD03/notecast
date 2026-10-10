#!/bin/bash

# Target the simulations folder inside your web directory
BASE_DIR="web/simulations"

echo "📂 Setting up simulation directory structure inside web/simulations/..."

# 1. School of Technology & Computing
TECH=(
  "Artificial_Intelligence" "Bioinformatics" "Blockchain_Technology" "Building_and_Construction_Technology" 
  "Cloud_Computing" "Computer_Animation" "Computer_Engineering" "Computer_Information_Systems_CIS" 
  "Computer_Science" "Cybersecurity_and_Cyber_Defense" "Data_Science_and_Analytics" "Database_Management_Systems" 
  "Digital_Forensics" "Educational_Technology" "Electrical_and_Electronics_Technology" "Game_Development" 
  "Geographic_Information_Systems_GIS" "Health_Information_Management" "Information_Communication_Technology_ICT" 
  "Information_Science" "Information_Technology_IT" "Instrumentation_and_Control_Systems_Technology" 
  "Internet_of_Things_IoT" "Management_Information_Systems_MIS" "Mobile_Application_Development" "Multimedia_Technology" 
  "Network_Administration" "Robotics_and_Mechatronics" "Software_Engineering" "Telecommunications_Engineering" 
  "Virtual_and_Augmented_Reality_VR_AR" "Web_Design_and_Development"
)

# 2. School of Engineering
ENG=(
  "Aerospace_Engineering" "Agricultural_Engineering" "Automotive_Engineering" "Bioengineering" 
  "Biomedical_Engineering" "Chemical_Engineering" "Civil_Engineering" "Computer_Engineering" 
  "Electrical_Engineering" "Environmental_Engineering" "Industrial_Engineering" "Materials_Science_and_Engineering" 
  "Mechanical_Engineering" "Mechatronics_Engineering" "Mining_Engineering" "Nuclear_Engineering" 
  "Petroleum_Engineering" "Robotics_Engineering" "Software_Engineering" "Structural_Engineering" "Systems_Engineering"
)

# 3. School of Education
EDU=(
  "BEd_Science_Mathematics_and_Physics" "BEd_Science_Biology_and_Chemistry" "BEd_Arts_Geography_and_Mathematics" 
  "BEd_Computer_Science" "MEd_Mathematics_Education" "MEd_Science_Education" "PGDE_Science_STEM" 
  "BEd_Technology_Education" "Diploma_in_Teacher_Education_Science"
)

# 4. School of Business
BUS=(
  "Accounting" "Actuarial_Science" "Banking_and_Finance" "Business_Administration" "Business_Analytics" 
  "Business_Communication" "Commerce_BCom" "Corporate_Governance" "E_Commerce" "Entrepreneurship_and_Innovation" 
  "Financial_Engineering" "Hospitality_and_Tourism_Management" "Human_Resource_Management" "International_Business" 
  "Logistics_and_Supply_Chain_Management" "Management_Information_Systems_MIS" "Marketing_and_Digital_Strategy" 
  "Operations_Management" "Project_Management" "Real_Estate_Management" "Strategic_Management"
)

build_structure() {
  local faculty=$1
  shift
  local courses=("$@")
  
  for course in "${courses[@]}"; do
    DIR="$BASE_DIR/$faculty/$course"
    mkdir -p "$DIR"
    # Create empty placeholder files for core syllabus modules
    touch "$DIR/fundamentals.html"
    touch "$DIR/advanced_architecture.html"
    touch "$DIR/case_study_simulation.html"
  done
}

# Execute creation for all faculties under web/simulations/
build_structure "Technology" "${TECH[@]}"
build_structure "Engineering" "${ENG[@]}"
build_structure "Education" "${EDU[@]}"
build_structure "Business" "${BUS[@]}"

echo "✅ Successfully set up the entire simulation directory hierarchy under $BASE_DIR!"
